# CircuitSetup Energy Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-installable Home Assistant custom integration that learns per-circuit power-quality baselines from CircuitSetup 6 Channel Energy Meter ESPHome ATM90E32 sensors and exposes conservative diagnostic alerts.

**Architecture:** Implement the analyzer as a Home Assistant custom integration under `custom_components/circuitsetup_energy_analyzer`. Keep appliance-analysis logic in pure Python modules with focused unit tests, then connect it to Home Assistant through config flows, event-driven source sensor tracking, diagnostic entities, persistent notifications, Repairs, and a compact integration-owned feature store.

**Tech Stack:** Python 3.13, Home Assistant custom integration APIs, HACS repository layout, pytest, pytest-homeassistant-custom-component, voluptuous, Home Assistant `Store`, `DataUpdateCoordinator`, `SensorEntity`, `BinarySensorEntity`, and `async_track_state_change_event`.

---

## Source References

- Design spec: `docs/superpowers/specs/2026-06-02-circuitsetup-energy-analyzer-design.md`
- Home Assistant config flow docs: `https://developers.home-assistant.io/docs/core/integration/config_flow`
- Home Assistant options flow docs: `https://developers.home-assistant.io/docs/core/integration/options_flow/`
- Home Assistant event listener docs: `https://developers.home-assistant.io/docs/integration_listen_events`
- Home Assistant sensor entity docs: `https://developers.home-assistant.io/docs/core/entity/sensor/`
- Home Assistant Repairs docs: `https://developers.home-assistant.io/docs/core/platform/repairs/`
- HACS integration publishing docs: `https://hacs.xyz/docs/publish/integration/`
- ESPHome ATM90E32 docs: `https://esphome.io/components/sensor/atm90e32/`

## File Structure

Create this structure:

```text
custom_components/circuitsetup_energy_analyzer/
  __init__.py                  # HA setup, unload, config entry migration, runtime lifecycle
  alerting.py                  # Conservative repeated-evidence alert policy and messages
  aggregation.py               # Dual-phase sample aggregation and imbalance checks
  baseline.py                  # Robust rolling baseline statistics and confidence scoring
  binary_sensor.py             # HA binary diagnostic entities
  config_flow.py               # UI setup and options flow
  const.py                     # Domain, platforms, defaults, storage keys, units
  coordinator.py               # Event-driven runtime coordinator for source sensor changes
  diagnostics.py               # Redacted HA diagnostics export
  discovery.py                 # Sensor discovery and entity metadata extraction
  entity.py                    # Shared entity base classes
  events.py                    # Circuit event detection
  manifest.json                # HA integration manifest
  mapping.py                   # Channel grouping and dual-phase suggestions
  models.py                    # Dataclasses/enums shared by the analyzer
  normalize.py                 # HA state to normalized circuit sample conversion
  notifications.py             # Persistent notification helpers
  profiles.py                  # Appliance profile definitions and thresholds
  repairs.py                   # HA Repairs issue creation and fix flow entrypoint
  sensor.py                    # HA sensor diagnostic entities
  services.py                  # Integration services/actions
  services.yaml                # Service schema descriptions
  storage.py                   # Integration-owned feature/event store
  strings.json                 # Config flow, service, and repair translations
docs/
  dashboard-example.yaml       # Optional example dashboard using standard HA entities
  superpowers/plans/2026-06-02-circuitsetup-energy-analyzer.md
  superpowers/specs/2026-06-02-circuitsetup-energy-analyzer-design.md
tests/
  conftest.py
  fixtures.py
  test_alerting.py
  test_aggregation.py
  test_baseline.py
  test_config_flow.py
  test_coordinator.py
  test_discovery.py
  test_entities.py
  test_events.py
  test_mapping.py
  test_normalize.py
  test_profiles.py
  test_services.py
  test_storage.py
.gitignore
hacs.json
pyproject.toml
README.md
```

## Implementation Tasks

### Task 1: Repository And Integration Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `hacs.json`
- Create: `custom_components/circuitsetup_energy_analyzer/__init__.py`
- Create: `custom_components/circuitsetup_energy_analyzer/manifest.json`
- Create: `custom_components/circuitsetup_energy_analyzer/const.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write the failing scaffold test**

Create `tests/test_profiles.py` with this initial smoke test:

```python
from custom_components.circuitsetup_energy_analyzer.const import DOMAIN


def test_domain_is_stable() -> None:
    assert DOMAIN == "circuitsetup_energy_analyzer"
```

- [ ] **Step 2: Run the scaffold test to verify it fails**

Run:

```bash
python -m pytest tests/test_profiles.py -q
```

Expected: FAIL with an import error for `custom_components.circuitsetup_energy_analyzer.const`.

- [ ] **Step 3: Create project and integration metadata**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=70.0"]
build-backend = "setuptools.build_meta"

[project]
name = "circuitsetup-energy-analyzer"
version = "0.1.0"
description = "Home Assistant custom integration for CircuitSetup Energy Meter appliance diagnostics"
requires-python = ">=3.13"
dependencies = [
  "homeassistant>=2026.5.0",
  "voluptuous>=0.15.2",
]

[project.optional-dependencies]
test = [
  "pytest>=8.3.0",
  "pytest-asyncio>=0.25.0",
  "pytest-homeassistant-custom-component>=0.13.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 88
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "T20"]
```

Create `.gitignore`:

```gitignore
.pytest_cache/
.ruff_cache/
.venv/
__pycache__/
*.py[cod]
.coverage
htmlcov/
```

Create `README.md`:

```markdown
# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration for analyzing CircuitSetup 6 Channel Energy Meter data exposed by ESPHome ATM90E32 sensors.

The integration learns conservative per-circuit baselines for single-phase appliances, dual-phase appliances, and mixed or unprofiled circuits. It exposes diagnostic entities, persistent notifications for important events, and Repairs for integration or source-data problems.

## Installation

This repository is structured for HACS as a custom integration. The integration files live under `custom_components/circuitsetup_energy_analyzer`.
```

Create `hacs.json`:

```json
{
  "name": "CircuitSetup Energy Analyzer",
  "render_readme": true,
  "homeassistant": "2026.5.0"
}
```

Create `custom_components/circuitsetup_energy_analyzer/manifest.json`:

```json
{
  "domain": "circuitsetup_energy_analyzer",
  "name": "CircuitSetup Energy Analyzer",
  "after_dependencies": ["esphome", "sensor"],
  "codeowners": ["@CircuitSetup"],
  "config_flow": true,
  "documentation": "https://github.com/CircuitSetup/CS_energy_analyzer",
  "integration_type": "helper",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/CircuitSetup/CS_energy_analyzer/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

Create `custom_components/circuitsetup_energy_analyzer/__init__.py`:

```python
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS

type CircuitSetupEnergyAnalyzerConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Set up CircuitSetup Energy Analyzer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Unload CircuitSetup Energy Analyzer."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
```

Create `custom_components/circuitsetup_energy_analyzer/const.py`:

```python
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "circuitsetup_energy_analyzer"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_CIRCUITS = "circuits"
CONF_RETENTION_MODE = "retention_mode"
CONF_SENSITIVITY = "sensitivity"
CONF_SOURCE_ENTITIES = "source_entities"

DEFAULT_SENSITIVITY = "standard"
DEFAULT_RETENTION_MODE = "standard"

STORAGE_KEY = f"{DOMAIN}.store"
STORAGE_VERSION = 1

MIN_LEARNING_DAYS = 7
```

Create `tests/conftest.py`:

```python
pytest_plugins = "pytest_homeassistant_custom_component"
```

- [ ] **Step 4: Run the scaffold test to verify it passes**

Run:

```bash
python -m pytest tests/test_profiles.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit scaffold**

Run:

```bash
git add .gitignore README.md hacs.json pyproject.toml custom_components/circuitsetup_energy_analyzer/__init__.py custom_components/circuitsetup_energy_analyzer/manifest.json custom_components/circuitsetup_energy_analyzer/const.py tests/conftest.py tests/test_profiles.py
git commit -m "chore: scaffold energy analyzer integration"
```

### Task 2: Core Models And Appliance Profiles

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/models.py`
- Create: `custom_components/circuitsetup_energy_analyzer/profiles.py`
- Modify: `tests/test_profiles.py`

- [ ] **Step 1: Write failing model/profile tests**

Replace `tests/test_profiles.py` with:

```python
from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitMode,
    RetentionMode,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.profiles import (
    get_profile_definition,
)


def test_domain_is_stable() -> None:
    assert DOMAIN == "circuitsetup_energy_analyzer"


def test_refrigerator_profile_requires_single_phase_power_roles() -> None:
    profile = get_profile_definition(ApplianceProfile.REFRIGERATOR)

    assert profile.appliance_profile is ApplianceProfile.REFRIGERATOR
    assert profile.supported_modes == {CircuitMode.SINGLE_PHASE}
    assert SensorRole.REAL_POWER in profile.required_roles
    assert SensorRole.CURRENT in profile.required_roles
    assert SensorRole.REACTIVE_POWER in profile.recommended_roles
    assert profile.minimum_cycles >= 20


def test_hvac_profile_supports_dual_phase_and_voltage_context() -> None:
    profile = get_profile_definition(ApplianceProfile.HVAC)

    assert CircuitMode.DUAL_PHASE in profile.supported_modes
    assert SensorRole.VOLTAGE in profile.recommended_roles
    assert "leg_imbalance" in profile.features


def test_retention_modes_are_user_visible_values() -> None:
    assert {mode.value for mode in RetentionMode} == {
        "lightweight",
        "standard",
        "diagnostic",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_profiles.py -q
```

Expected: FAIL with an import error for `models`.

- [ ] **Step 3: Add core dataclasses and enums**

Create `custom_components/circuitsetup_energy_analyzer/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ApplianceProfile(StrEnum):
    """Supported appliance profile families."""

    REFRIGERATOR = "refrigerator"
    FREEZER = "freezer"
    HVAC = "hvac"
    WATER_HEATER = "water_heater"
    OVEN = "oven"
    DRYER = "dryer"
    POOL_PUMP = "pool_pump"
    WELL_PUMP = "well_pump"
    SUMP_PUMP = "sump_pump"
    EV_CHARGER = "ev_charger"
    MOTOR_LOAD = "motor_load"
    RESISTIVE_LOAD = "resistive_load"
    MIXED = "mixed"


class CircuitMode(StrEnum):
    """Configured circuit analysis mode."""

    SINGLE_PHASE = "single_phase"
    DUAL_PHASE = "dual_phase"
    MIXED = "mixed"


class RetentionMode(StrEnum):
    """Feature-store retention levels."""

    LIGHTWEIGHT = "lightweight"
    STANDARD = "standard"
    DIAGNOSTIC = "diagnostic"


class SensorRole(StrEnum):
    """Source sensor role used by the analyzer."""

    VOLTAGE = "voltage"
    CURRENT = "current"
    REAL_POWER = "real_power"
    REACTIVE_POWER = "reactive_power"
    APPARENT_POWER = "apparent_power"
    POWER_FACTOR = "power_factor"
    FREQUENCY = "frequency"
    ENERGY = "energy"


class EventType(StrEnum):
    """Analyzer event type."""

    START = "start"
    STOP = "stop"
    STEADY_WINDOW = "steady_window"
    VOLTAGE_SAG = "voltage_sag"
    VOLTAGE_SWELL = "voltage_swell"
    LEG_IMBALANCE = "leg_imbalance"
    DATA_QUALITY = "data_quality"


class Severity(StrEnum):
    """User-facing alert severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SensorRef:
    """Reference to a Home Assistant source sensor."""

    entity_id: str
    role: SensorRole
    phase: str | None = None
    leg: str | None = None


@dataclass(frozen=True, slots=True)
class CircuitConfig:
    """User-configured circuit definition."""

    circuit_id: str
    name: str
    mode: CircuitMode
    appliance_profile: ApplianceProfile
    sensors: tuple[SensorRef, ...]
    sensitivity: str = "standard"
    retention_mode: RetentionMode = RetentionMode.STANDARD
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class CircuitSample:
    """Normalized sample for one circuit at one time."""

    circuit_id: str
    timestamp: datetime
    voltage: float | None = None
    current: float | None = None
    real_power_w: float | None = None
    reactive_power_var: float | None = None
    apparent_power_va: float | None = None
    power_factor: float | None = None
    frequency_hz: float | None = None
    source_entity_ids: tuple[str, ...] = ()
    quality_issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LegSample:
    """Normalized sample for one leg of a dual-phase circuit."""

    leg_id: str
    voltage: float | None
    current: float | None
    real_power_w: float | None
    reactive_power_var: float | None
    apparent_power_va: float | None
    power_factor: float | None


@dataclass(frozen=True, slots=True)
class DualPhaseSample:
    """Aggregated dual-phase sample with leg-level detail."""

    circuit_id: str
    timestamp: datetime
    combined: CircuitSample
    legs: tuple[LegSample, LegSample]
    leg_power_imbalance_ratio: float | None
    voltage_difference: float | None
    quality_issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CircuitEvent:
    """Derived event stored for baseline and alert analysis."""

    circuit_id: str
    event_type: EventType
    started_at: datetime
    ended_at: datetime | None = None
    features: dict[str, float] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BaselineStats:
    """Robust baseline for one feature."""

    feature: str
    sample_count: int
    median: float
    mad: float
    p10: float
    p90: float
    confidence: float


@dataclass(frozen=True, slots=True)
class AlertEvidence:
    """Evidence for a conservative alert."""

    circuit_id: str
    feature: str
    severity: Severity
    message: str
    observed_value: float
    baseline_value: float
    change_ratio: float
    repeated_count: int
    first_seen: datetime
    last_seen: datetime
```

- [ ] **Step 4: Add profile definitions**

Create `custom_components/circuitsetup_energy_analyzer/profiles.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from .models import ApplianceProfile, CircuitMode, SensorRole


@dataclass(frozen=True, slots=True)
class ProfileDefinition:
    """Analysis settings for an appliance profile."""

    appliance_profile: ApplianceProfile
    supported_modes: set[CircuitMode]
    required_roles: set[SensorRole]
    recommended_roles: set[SensorRole]
    features: set[str]
    minimum_cycles: int
    minimum_learning_days: int


REAL_POWER_CORE = {SensorRole.REAL_POWER, SensorRole.CURRENT}
POWER_QUALITY_RECOMMENDED = {
    SensorRole.VOLTAGE,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.FREQUENCY,
}

PROFILE_DEFINITIONS: dict[ApplianceProfile, ProfileDefinition] = {
    ApplianceProfile.REFRIGERATOR: ProfileDefinition(
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        supported_modes={CircuitMode.SINGLE_PHASE},
        required_roles=REAL_POWER_CORE,
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "cycle_duration",
            "off_interval",
            "duty_cycle",
            "steady_real_power",
            "steady_reactive_power",
            "steady_power_factor",
            "startup_spike",
            "short_cycling",
        },
        minimum_cycles=20,
        minimum_learning_days=7,
    ),
    ApplianceProfile.FREEZER: ProfileDefinition(
        appliance_profile=ApplianceProfile.FREEZER,
        supported_modes={CircuitMode.SINGLE_PHASE},
        required_roles=REAL_POWER_CORE,
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "cycle_duration",
            "off_interval",
            "duty_cycle",
            "steady_real_power",
            "steady_reactive_power",
            "steady_power_factor",
            "startup_spike",
            "short_cycling",
        },
        minimum_cycles=20,
        minimum_learning_days=7,
    ),
    ApplianceProfile.HVAC: ProfileDefinition(
        appliance_profile=ApplianceProfile.HVAC,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles=REAL_POWER_CORE,
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "cycle_duration",
            "short_cycling",
            "startup_spike",
            "steady_real_power",
            "steady_reactive_power",
            "steady_power_factor",
            "voltage_sag",
            "leg_imbalance",
        },
        minimum_cycles=15,
        minimum_learning_days=7,
    ),
    ApplianceProfile.WATER_HEATER: ProfileDefinition(
        appliance_profile=ApplianceProfile.WATER_HEATER,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles={SensorRole.REAL_POWER},
        recommended_roles={SensorRole.VOLTAGE, SensorRole.POWER_FACTOR},
        features={"heating_duration", "steady_real_power", "leg_imbalance"},
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.OVEN: ProfileDefinition(
        appliance_profile=ApplianceProfile.OVEN,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles={SensorRole.REAL_POWER},
        recommended_roles={SensorRole.VOLTAGE, SensorRole.POWER_FACTOR},
        features={"heating_duration", "steady_real_power", "leg_imbalance"},
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.DRYER: ProfileDefinition(
        appliance_profile=ApplianceProfile.DRYER,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles={SensorRole.REAL_POWER},
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={"cycle_duration", "steady_real_power", "leg_imbalance"},
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.POOL_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.POOL_PUMP,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles=REAL_POWER_CORE,
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "run_duration",
            "run_frequency",
            "startup_spike",
            "steady_reactive_power",
            "steady_power_factor",
            "voltage_sag",
        },
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.WELL_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.WELL_PUMP,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles=REAL_POWER_CORE,
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "run_duration",
            "run_frequency",
            "startup_spike",
            "steady_reactive_power",
            "steady_power_factor",
            "voltage_sag",
        },
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.SUMP_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.SUMP_PUMP,
        supported_modes={CircuitMode.SINGLE_PHASE},
        required_roles=REAL_POWER_CORE,
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "run_duration",
            "run_frequency",
            "startup_spike",
            "steady_reactive_power",
            "steady_power_factor",
            "voltage_sag",
        },
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.EV_CHARGER: ProfileDefinition(
        appliance_profile=ApplianceProfile.EV_CHARGER,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles={SensorRole.REAL_POWER, SensorRole.CURRENT},
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "session_duration",
            "power_ramp",
            "steady_real_power",
            "steady_power_factor",
            "voltage_sag",
        },
        minimum_cycles=5,
        minimum_learning_days=7,
    ),
    ApplianceProfile.MOTOR_LOAD: ProfileDefinition(
        appliance_profile=ApplianceProfile.MOTOR_LOAD,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles=REAL_POWER_CORE,
        recommended_roles=POWER_QUALITY_RECOMMENDED,
        features={
            "run_duration",
            "startup_spike",
            "steady_reactive_power",
            "steady_power_factor",
            "voltage_sag",
        },
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.RESISTIVE_LOAD: ProfileDefinition(
        appliance_profile=ApplianceProfile.RESISTIVE_LOAD,
        supported_modes={CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE},
        required_roles={SensorRole.REAL_POWER},
        recommended_roles={SensorRole.VOLTAGE, SensorRole.POWER_FACTOR},
        features={"steady_real_power", "leg_imbalance"},
        minimum_cycles=10,
        minimum_learning_days=7,
    ),
    ApplianceProfile.MIXED: ProfileDefinition(
        appliance_profile=ApplianceProfile.MIXED,
        supported_modes={CircuitMode.MIXED},
        required_roles={SensorRole.REAL_POWER},
        recommended_roles={SensorRole.VOLTAGE, SensorRole.CURRENT},
        features={"large_persistent_change", "feed_quality"},
        minimum_cycles=0,
        minimum_learning_days=0,
    ),
}


def get_profile_definition(profile: ApplianceProfile) -> ProfileDefinition:
    """Return the profile definition for an appliance profile."""
    return PROFILE_DEFINITIONS[profile]
```

- [ ] **Step 5: Run model/profile tests**

Run:

```bash
python -m pytest tests/test_profiles.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit models and profiles**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/models.py custom_components/circuitsetup_energy_analyzer/profiles.py tests/test_profiles.py
git commit -m "feat: add analyzer models and appliance profiles"
```

### Task 3: Sensor Discovery And Role Inference

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/discovery.py`
- Create: `tests/test_discovery.py`

- [ ] **Step 1: Write failing discovery tests**

Create `tests/test_discovery.py`:

```python
from custom_components.circuitsetup_energy_analyzer.discovery import (
    DiscoveredSensor,
    infer_sensor_role,
    score_circuitsetup_candidate,
)
from custom_components.circuitsetup_energy_analyzer.models import SensorRole


def test_infer_sensor_roles_from_entity_names() -> None:
    assert infer_sensor_role("sensor.energy_meter_voltage_a", "Voltage A") is SensorRole.VOLTAGE
    assert infer_sensor_role("sensor.energy_meter_current_1", "Current 1") is SensorRole.CURRENT
    assert infer_sensor_role("sensor.energy_meter_power_1", "Power 1") is SensorRole.REAL_POWER
    assert infer_sensor_role("sensor.energy_meter_reactive_power_1", "Reactive Power 1") is SensorRole.REACTIVE_POWER
    assert infer_sensor_role("sensor.energy_meter_apparent_power_1", "Apparent Power 1") is SensorRole.APPARENT_POWER
    assert infer_sensor_role("sensor.energy_meter_power_factor_1", "Power Factor 1") is SensorRole.POWER_FACTOR


def test_candidate_scoring_prefers_atm90e32_metadata() -> None:
    sensor = DiscoveredSensor(
        entity_id="sensor.circuitsetup_energy_meter_power_1",
        name="CircuitSetup Energy Meter Power 1",
        role=SensorRole.REAL_POWER,
        device_id="device-1",
        unit="W",
        device_class="power",
        integration_domain="esphome",
    )

    assert score_circuitsetup_candidate(sensor) >= 5
```

- [ ] **Step 2: Run discovery tests to verify they fail**

Run:

```bash
python -m pytest tests/test_discovery.py -q
```

Expected: FAIL with an import error for `discovery`.

- [ ] **Step 3: Implement discovery helpers**

Create `custom_components/circuitsetup_energy_analyzer/discovery.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .models import SensorRole


@dataclass(frozen=True, slots=True)
class DiscoveredSensor:
    """Entity metadata used during setup."""

    entity_id: str
    name: str
    role: SensorRole | None
    device_id: str | None
    unit: str | None
    device_class: str | None
    integration_domain: str | None


ROLE_KEYWORDS: tuple[tuple[SensorRole, tuple[str, ...]], ...] = (
    (SensorRole.REACTIVE_POWER, ("reactive_power", "reactive power", "var")),
    (SensorRole.APPARENT_POWER, ("apparent_power", "apparent power", "va")),
    (SensorRole.POWER_FACTOR, ("power_factor", "power factor", "pf")),
    (SensorRole.REAL_POWER, ("real_power", "power ", "_power_", " watts", "watt")),
    (SensorRole.CURRENT, ("current", "amps", " amp", "_a")),
    (SensorRole.VOLTAGE, ("voltage", "volts", " volt", "_v")),
    (SensorRole.FREQUENCY, ("frequency", "hz")),
    (SensorRole.ENERGY, ("energy", "kwh", "wh")),
)


def infer_sensor_role(entity_id: str, friendly_name: str | None) -> SensorRole | None:
    """Infer analyzer role from entity id and friendly name."""
    haystack = f"{entity_id} {friendly_name or ''}".replace(".", "_").lower()
    for role, keywords in ROLE_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return role
    return None


def score_circuitsetup_candidate(sensor: DiscoveredSensor) -> int:
    """Score whether a discovered sensor belongs to a CircuitSetup meter."""
    text = f"{sensor.entity_id} {sensor.name}".lower()
    score = 0
    if sensor.integration_domain == "esphome":
        score += 2
    if "circuitsetup" in text:
        score += 2
    if "energy" in text or "meter" in text:
        score += 1
    if sensor.role is not None:
        score += 1
    if sensor.device_class in {"power", "voltage", "current", "energy", "power_factor", "frequency"}:
        score += 1
    return score


def async_discover_sensors(hass: HomeAssistant) -> list[DiscoveredSensor]:
    """Discover candidate source sensors from the entity registry and state machine."""
    registry = er.async_get(hass)
    sensors: list[DiscoveredSensor] = []

    for entity in registry.entities.values():
        if not entity.entity_id.startswith("sensor."):
            continue

        state = hass.states.get(entity.entity_id)
        attrs = state.attributes if state is not None else {}
        friendly_name = attrs.get("friendly_name") or entity.name or entity.original_name or entity.entity_id
        role = infer_sensor_role(entity.entity_id, friendly_name)
        discovered = DiscoveredSensor(
            entity_id=entity.entity_id,
            name=str(friendly_name),
            role=role,
            device_id=entity.device_id,
            unit=attrs.get("unit_of_measurement"),
            device_class=attrs.get("device_class"),
            integration_domain=entity.platform,
        )
        if score_circuitsetup_candidate(discovered) >= 3:
            sensors.append(discovered)

    return sorted(sensors, key=lambda item: item.entity_id)
```

- [ ] **Step 4: Run discovery tests**

Run:

```bash
python -m pytest tests/test_discovery.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit discovery**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/discovery.py tests/test_discovery.py
git commit -m "feat: discover energy meter source sensors"
```

### Task 4: Channel Mapping And Dual-Phase Suggestions

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/mapping.py`
- Create: `tests/test_mapping.py`

- [ ] **Step 1: Write failing mapping tests**

Create `tests/test_mapping.py`:

```python
from custom_components.circuitsetup_energy_analyzer.discovery import DiscoveredSensor
from custom_components.circuitsetup_energy_analyzer.mapping import (
    ChannelGroup,
    suggest_dual_phase_pairs,
)
from custom_components.circuitsetup_energy_analyzer.models import SensorRole


def sensor(entity_id: str, name: str, role: SensorRole) -> DiscoveredSensor:
    return DiscoveredSensor(
        entity_id=entity_id,
        name=name,
        role=role,
        device_id="meter-1",
        unit=None,
        device_class=None,
        integration_domain="esphome",
    )


def test_dual_phase_suggestions_pair_neighboring_channels() -> None:
    candidates = [
        sensor("sensor.panel_ch1_power", "HVAC L1 Power", SensorRole.REAL_POWER),
        sensor("sensor.panel_ch2_power", "HVAC L2 Power", SensorRole.REAL_POWER),
        sensor("sensor.panel_ch3_power", "Fridge Power", SensorRole.REAL_POWER),
    ]

    suggestions = suggest_dual_phase_pairs(candidates)

    assert suggestions[0].left.entity_id == "sensor.panel_ch1_power"
    assert suggestions[0].right.entity_id == "sensor.panel_ch2_power"
    assert suggestions[0].confidence >= 0.6
    assert "neighboring channels" in suggestions[0].reasons


def test_channel_group_rejects_missing_real_power() -> None:
    group = ChannelGroup(
        group_id="fridge",
        sensors=(sensor("sensor.fridge_voltage", "Fridge Voltage", SensorRole.VOLTAGE),),
    )

    assert not group.has_role(SensorRole.REAL_POWER)
```

- [ ] **Step 2: Run mapping tests to verify they fail**

Run:

```bash
python -m pytest tests/test_mapping.py -q
```

Expected: FAIL with an import error for `mapping`.

- [ ] **Step 3: Implement mapping**

Create `custom_components/circuitsetup_energy_analyzer/mapping.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import re

from .discovery import DiscoveredSensor
from .models import SensorRole


@dataclass(frozen=True, slots=True)
class ChannelGroup:
    """A set of sensors that describe one channel."""

    group_id: str
    sensors: tuple[DiscoveredSensor, ...]

    def has_role(self, role: SensorRole) -> bool:
        """Return whether the channel has a sensor role."""
        return any(sensor.role is role for sensor in self.sensors)


@dataclass(frozen=True, slots=True)
class DualPhaseSuggestion:
    """Candidate pair for a dual-phase circuit."""

    left: DiscoveredSensor
    right: DiscoveredSensor
    confidence: float
    reasons: tuple[str, ...]


CHANNEL_PATTERN = re.compile(r"(?:ch|channel|ct)[ _-]*(\d+)", re.IGNORECASE)


def _extract_channel_number(sensor: DiscoveredSensor) -> int | None:
    text = f"{sensor.entity_id} {sensor.name}"
    match = CHANNEL_PATTERN.search(text)
    if match is None:
        return None
    return int(match.group(1))


def _shared_name_tokens(left: DiscoveredSensor, right: DiscoveredSensor) -> set[str]:
    noise = {"power", "real", "channel", "ch", "ct", "l1", "l2", "leg", "phase"}
    left_tokens = set(re.findall(r"[a-z0-9]+", left.name.lower())) - noise
    right_tokens = set(re.findall(r"[a-z0-9]+", right.name.lower())) - noise
    return left_tokens & right_tokens


def suggest_dual_phase_pairs(candidates: list[DiscoveredSensor]) -> list[DualPhaseSuggestion]:
    """Suggest dual-phase pairs from real-power source sensors."""
    power_sensors = [sensor for sensor in candidates if sensor.role is SensorRole.REAL_POWER]
    suggestions: list[DualPhaseSuggestion] = []

    for index, left in enumerate(power_sensors):
        left_channel = _extract_channel_number(left)
        for right in power_sensors[index + 1 :]:
            right_channel = _extract_channel_number(right)
            reasons: list[str] = []
            confidence = 0.0

            if left.device_id is not None and left.device_id == right.device_id:
                confidence += 0.25
                reasons.append("same device")

            if left_channel is not None and right_channel is not None:
                if abs(left_channel - right_channel) == 1:
                    confidence += 0.35
                    reasons.append("neighboring channels")

            shared_tokens = _shared_name_tokens(left, right)
            if shared_tokens:
                confidence += min(0.3, len(shared_tokens) * 0.15)
                reasons.append("similar names")

            if confidence >= 0.35:
                suggestions.append(
                    DualPhaseSuggestion(
                        left=left,
                        right=right,
                        confidence=min(confidence, 1.0),
                        reasons=tuple(reasons),
                    )
                )

    return sorted(suggestions, key=lambda item: item.confidence, reverse=True)
```

- [ ] **Step 4: Run mapping tests**

Run:

```bash
python -m pytest tests/test_mapping.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit mapping**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/mapping.py tests/test_mapping.py
git commit -m "feat: suggest circuit channel mappings"
```

### Task 5: Sample Normalization And Data Quality

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/normalize.py`
- Create: `tests/test_normalize.py`

- [ ] **Step 1: Write failing normalization tests**

Create `tests/test_normalize.py`:

```python
from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import CircuitConfig, CircuitMode, ApplianceProfile, SensorRef, SensorRole
from custom_components.circuitsetup_energy_analyzer.normalize import SourceState, build_circuit_sample


def test_build_circuit_sample_converts_kw_to_watts() -> None:
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_current", SensorRole.CURRENT),
        ),
    )
    now = datetime(2026, 6, 2, tzinfo=UTC)
    states = {
        "sensor.fridge_power": SourceState("sensor.fridge_power", "0.18", "kW", now),
        "sensor.fridge_current": SourceState("sensor.fridge_current", "1.7", "A", now),
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w == 180.0
    assert sample.current == 1.7
    assert sample.quality_issues == ()


def test_build_circuit_sample_marks_stale_and_unavailable_values() -> None:
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    now = datetime(2026, 6, 2, tzinfo=UTC)
    states = {
        "sensor.fridge_power": SourceState(
            "sensor.fridge_power",
            "unavailable",
            "W",
            now - timedelta(minutes=30),
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w is None
    assert "sensor.fridge_power unavailable" in sample.quality_issues
    assert "sensor.fridge_power stale" in sample.quality_issues
```

- [ ] **Step 2: Run normalization tests to verify they fail**

Run:

```bash
python -m pytest tests/test_normalize.py -q
```

Expected: FAIL with an import error for `normalize`.

- [ ] **Step 3: Implement normalization**

Create `custom_components/circuitsetup_energy_analyzer/normalize.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import CircuitConfig, CircuitSample, SensorRole

STALE_AFTER = timedelta(minutes=10)
UNAVAILABLE_STATES = {"unknown", "unavailable", ""}


@dataclass(frozen=True, slots=True)
class SourceState:
    """Minimal source-state representation for HA state normalization."""

    entity_id: str
    state: str
    unit: str | None
    last_updated: datetime


def _parse_number(source: SourceState, issues: list[str]) -> float | None:
    if source.state.lower() in UNAVAILABLE_STATES:
        issues.append(f"{source.entity_id} unavailable")
        return None
    try:
        return float(source.state)
    except ValueError:
        issues.append(f"{source.entity_id} non_numeric")
        return None


def _convert_power_to_watts(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    normalized_unit = (unit or "").strip().lower()
    if normalized_unit == "kw":
        return value * 1000.0
    return value


def _convert_energy_role_value(
    role: SensorRole,
    value: float | None,
    unit: str | None,
) -> float | None:
    if role in {
        SensorRole.REAL_POWER,
        SensorRole.REACTIVE_POWER,
        SensorRole.APPARENT_POWER,
    }:
        return _convert_power_to_watts(value, unit)
    return value


def build_circuit_sample(
    config: CircuitConfig,
    states: dict[str, SourceState],
    now: datetime,
) -> CircuitSample:
    """Build a normalized sample for one circuit."""
    values: dict[SensorRole, float | None] = {}
    issues: list[str] = []
    source_entity_ids: list[str] = []

    for sensor in config.sensors:
        source_entity_ids.append(sensor.entity_id)
        source = states.get(sensor.entity_id)
        if source is None:
            issues.append(f"{sensor.entity_id} missing")
            values[sensor.role] = None
            continue

        if now - source.last_updated > STALE_AFTER:
            issues.append(f"{sensor.entity_id} stale")

        value = _parse_number(source, issues)
        values[sensor.role] = _convert_energy_role_value(sensor.role, value, source.unit)

    return CircuitSample(
        circuit_id=config.circuit_id,
        timestamp=now,
        voltage=values.get(SensorRole.VOLTAGE),
        current=values.get(SensorRole.CURRENT),
        real_power_w=values.get(SensorRole.REAL_POWER),
        reactive_power_var=values.get(SensorRole.REACTIVE_POWER),
        apparent_power_va=values.get(SensorRole.APPARENT_POWER),
        power_factor=values.get(SensorRole.POWER_FACTOR),
        frequency_hz=values.get(SensorRole.FREQUENCY),
        source_entity_ids=tuple(source_entity_ids),
        quality_issues=tuple(issues),
    )
```

- [ ] **Step 4: Run normalization tests**

Run:

```bash
python -m pytest tests/test_normalize.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit normalization**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/normalize.py tests/test_normalize.py
git commit -m "feat: normalize source sensor samples"
```

### Task 6: Dual-Phase Aggregation

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/aggregation.py`
- Create: `tests/test_aggregation.py`

- [ ] **Step 1: Write failing aggregation tests**

Create `tests/test_aggregation.py`:

```python
from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.aggregation import aggregate_dual_phase
from custom_components.circuitsetup_energy_analyzer.models import CircuitSample


def sample(circuit_id: str, watts: float, volts: float) -> CircuitSample:
    return CircuitSample(
        circuit_id=circuit_id,
        timestamp=datetime(2026, 6, 2, tzinfo=UTC),
        voltage=volts,
        current=10.0,
        real_power_w=watts,
        reactive_power_var=100.0,
        apparent_power_va=watts + 50.0,
        power_factor=0.95,
    )


def test_aggregate_dual_phase_sums_power_and_tracks_imbalance() -> None:
    result = aggregate_dual_phase("hvac", sample("hvac_l1", 2400.0, 121.0), sample("hvac_l2", 1800.0, 119.0))

    assert result.combined.real_power_w == 4200.0
    assert result.combined.reactive_power_var == 200.0
    assert result.voltage_difference == 2.0
    assert round(result.leg_power_imbalance_ratio, 3) == 0.286


def test_aggregate_dual_phase_flags_one_leg_missing_power() -> None:
    result = aggregate_dual_phase("hvac", sample("hvac_l1", 2400.0, 121.0), sample("hvac_l2", 0.0, 119.0))

    assert "one_leg_low_power" in result.quality_issues
```

- [ ] **Step 2: Run aggregation tests to verify they fail**

Run:

```bash
python -m pytest tests/test_aggregation.py -q
```

Expected: FAIL with an import error for `aggregation`.

- [ ] **Step 3: Implement dual-phase aggregation**

Create `custom_components/circuitsetup_energy_analyzer/aggregation.py`:

```python
from __future__ import annotations

from .models import CircuitSample, DualPhaseSample, LegSample


def _sum_optional(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return (left or 0.0) + (right or 0.0)


def _average_optional(left: float | None, right: float | None) -> float | None:
    values = [value for value in (left, right) if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _imbalance_ratio(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    total = abs(left) + abs(right)
    if total == 0:
        return 0.0
    return abs(left - right) / total


def _leg_sample(leg_id: str, sample: CircuitSample) -> LegSample:
    return LegSample(
        leg_id=leg_id,
        voltage=sample.voltage,
        current=sample.current,
        real_power_w=sample.real_power_w,
        reactive_power_var=sample.reactive_power_var,
        apparent_power_va=sample.apparent_power_va,
        power_factor=sample.power_factor,
    )


def aggregate_dual_phase(
    circuit_id: str,
    left: CircuitSample,
    right: CircuitSample,
) -> DualPhaseSample:
    """Aggregate two leg samples into one dual-phase circuit sample."""
    imbalance = _imbalance_ratio(left.real_power_w, right.real_power_w)
    voltage_difference = (
        abs(left.voltage - right.voltage)
        if left.voltage is not None and right.voltage is not None
        else None
    )
    issues = list(left.quality_issues + right.quality_issues)

    left_watts = abs(left.real_power_w or 0.0)
    right_watts = abs(right.real_power_w or 0.0)
    if max(left_watts, right_watts) > 500.0 and min(left_watts, right_watts) < 50.0:
        issues.append("one_leg_low_power")

    combined = CircuitSample(
        circuit_id=circuit_id,
        timestamp=max(left.timestamp, right.timestamp),
        voltage=_average_optional(left.voltage, right.voltage),
        current=_sum_optional(left.current, right.current),
        real_power_w=_sum_optional(left.real_power_w, right.real_power_w),
        reactive_power_var=_sum_optional(left.reactive_power_var, right.reactive_power_var),
        apparent_power_va=_sum_optional(left.apparent_power_va, right.apparent_power_va),
        power_factor=_average_optional(left.power_factor, right.power_factor),
        frequency_hz=_average_optional(left.frequency_hz, right.frequency_hz),
        source_entity_ids=left.source_entity_ids + right.source_entity_ids,
        quality_issues=tuple(issues),
    )

    return DualPhaseSample(
        circuit_id=circuit_id,
        timestamp=combined.timestamp,
        combined=combined,
        legs=(_leg_sample("left", left), _leg_sample("right", right)),
        leg_power_imbalance_ratio=imbalance,
        voltage_difference=voltage_difference,
        quality_issues=tuple(issues),
    )
```

- [ ] **Step 4: Run aggregation tests**

Run:

```bash
python -m pytest tests/test_aggregation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit aggregation**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/aggregation.py tests/test_aggregation.py
git commit -m "feat: aggregate dual phase circuits"
```

### Task 7: Event Detection

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/events.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: Write failing event tests**

Create `tests/test_events.py`:

```python
from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.events import CircuitEventDetector
from custom_components.circuitsetup_energy_analyzer.models import CircuitSample, EventType


def sample(offset: int, watts: float, voltage: float = 120.0) -> CircuitSample:
    return CircuitSample(
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 2, tzinfo=UTC) + timedelta(seconds=offset),
        real_power_w=watts,
        voltage=voltage,
    )


def test_event_detector_emits_start_and_stop() -> None:
    detector = CircuitEventDetector(on_threshold_w=80.0, off_threshold_w=30.0)

    events = [
        *detector.process(sample(0, 5.0)),
        *detector.process(sample(10, 210.0)),
        *detector.process(sample(70, 185.0)),
        *detector.process(sample(130, 8.0)),
    ]

    assert [event.event_type for event in events] == [EventType.START, EventType.STOP]
    assert events[0].features["startup_power_w"] == 210.0
    assert events[1].features["run_duration_s"] == 120.0


def test_event_detector_emits_voltage_sag_under_load() -> None:
    detector = CircuitEventDetector(on_threshold_w=80.0, voltage_sag_ratio=0.08)

    detector.process(sample(0, 5.0, 120.0))
    events = detector.process(sample(10, 500.0, 109.0))

    assert events[0].event_type is EventType.START
    assert events[1].event_type is EventType.VOLTAGE_SAG
```

- [ ] **Step 2: Run event tests to verify they fail**

Run:

```bash
python -m pytest tests/test_events.py -q
```

Expected: FAIL with an import error for `events`.

- [ ] **Step 3: Implement event detection**

Create `custom_components/circuitsetup_energy_analyzer/events.py`:

```python
from __future__ import annotations

from .models import CircuitEvent, CircuitSample, EventType


class CircuitEventDetector:
    """Detect state transitions and feed-quality events for one circuit."""

    def __init__(
        self,
        *,
        on_threshold_w: float = 80.0,
        off_threshold_w: float = 30.0,
        voltage_sag_ratio: float = 0.08,
    ) -> None:
        self._on_threshold_w = on_threshold_w
        self._off_threshold_w = off_threshold_w
        self._voltage_sag_ratio = voltage_sag_ratio
        self._is_on = False
        self._run_started_at = None
        self._nominal_voltage = None
        self._last_power_w = 0.0

    def process(self, sample: CircuitSample) -> list[CircuitEvent]:
        """Process one sample and return detected events."""
        events: list[CircuitEvent] = []
        watts = sample.real_power_w or 0.0

        if sample.voltage is not None and not self._is_on:
            self._nominal_voltage = sample.voltage

        if not self._is_on and watts >= self._on_threshold_w:
            self._is_on = True
            self._run_started_at = sample.timestamp
            events.append(
                CircuitEvent(
                    circuit_id=sample.circuit_id,
                    event_type=EventType.START,
                    started_at=sample.timestamp,
                    features={
                        "startup_power_w": watts,
                        "previous_power_w": self._last_power_w,
                    },
                )
            )

        if self._is_on and sample.voltage is not None and self._nominal_voltage:
            sag_ratio = (self._nominal_voltage - sample.voltage) / self._nominal_voltage
            if sag_ratio >= self._voltage_sag_ratio:
                events.append(
                    CircuitEvent(
                        circuit_id=sample.circuit_id,
                        event_type=EventType.VOLTAGE_SAG,
                        started_at=sample.timestamp,
                        features={
                            "voltage": sample.voltage,
                            "nominal_voltage": self._nominal_voltage,
                            "sag_ratio": sag_ratio,
                            "real_power_w": watts,
                        },
                    )
                )

        if self._is_on and watts <= self._off_threshold_w:
            run_started_at = self._run_started_at or sample.timestamp
            self._is_on = False
            self._run_started_at = None
            events.append(
                CircuitEvent(
                    circuit_id=sample.circuit_id,
                    event_type=EventType.STOP,
                    started_at=run_started_at,
                    ended_at=sample.timestamp,
                    features={
                        "run_duration_s": (sample.timestamp - run_started_at).total_seconds(),
                        "stop_power_w": watts,
                    },
                )
            )

        self._last_power_w = watts
        return events
```

- [ ] **Step 4: Run event tests**

Run:

```bash
python -m pytest tests/test_events.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit event detection**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/events.py tests/test_events.py
git commit -m "feat: detect circuit operating events"
```

### Task 8: Baseline Learning

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/baseline.py`
- Create: `tests/test_baseline.py`

- [ ] **Step 1: Write failing baseline tests**

Create `tests/test_baseline.py`:

```python
from custom_components.circuitsetup_energy_analyzer.baseline import (
    build_baseline,
    score_deviation,
)


def test_build_baseline_uses_robust_statistics() -> None:
    baseline = build_baseline("cycle_duration", [100, 101, 99, 100, 102, 100, 900])

    assert baseline.median == 100.0
    assert baseline.p90 == 102.0
    assert baseline.sample_count == 7
    assert baseline.confidence > 0.4


def test_score_deviation_requires_meaningful_change() -> None:
    baseline = build_baseline("steady_reactive_power", [100, 105, 95, 98, 102, 100, 103, 97])

    assert score_deviation(104.0, baseline) < 1.0
    assert score_deviation(160.0, baseline) > 3.0
```

- [ ] **Step 2: Run baseline tests to verify they fail**

Run:

```bash
python -m pytest tests/test_baseline.py -q
```

Expected: FAIL with an import error for `baseline`.

- [ ] **Step 3: Implement robust baseline functions**

Create `custom_components/circuitsetup_energy_analyzer/baseline.py`:

```python
from __future__ import annotations

from statistics import median

from .models import BaselineStats


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("cannot calculate percentile for empty values")
    index = round((len(sorted_values) - 1) * percentile)
    return sorted_values[index]


def build_baseline(feature: str, values: list[float]) -> BaselineStats:
    """Build robust baseline stats for one feature."""
    if not values:
        raise ValueError("baseline requires at least one value")

    sorted_values = sorted(float(value) for value in values)
    med = float(median(sorted_values))
    deviations = [abs(value - med) for value in sorted_values]
    mad = float(median(deviations))
    sample_count = len(sorted_values)
    confidence = min(1.0, sample_count / 20.0)

    return BaselineStats(
        feature=feature,
        sample_count=sample_count,
        median=med,
        mad=mad,
        p10=_percentile(sorted_values, 0.10),
        p90=_percentile(sorted_values, 0.90),
        confidence=confidence,
    )


def score_deviation(observed: float, baseline: BaselineStats) -> float:
    """Return robust absolute deviation score from baseline."""
    spread = max(baseline.mad * 1.4826, abs(baseline.median) * 0.05, 1.0)
    return abs(observed - baseline.median) / spread
```

- [ ] **Step 4: Run baseline tests**

Run:

```bash
python -m pytest tests/test_baseline.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit baseline**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/baseline.py tests/test_baseline.py
git commit -m "feat: learn robust circuit baselines"
```

### Task 9: Conservative Alert Policy

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/alerting.py`
- Create: `tests/test_alerting.py`

- [ ] **Step 1: Write failing alerting tests**

Create `tests/test_alerting.py`:

```python
from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.alerting import ConservativeAlertPolicy, Observation


def test_policy_waits_for_repeated_observations() -> None:
    policy = ConservativeAlertPolicy(min_repeated=3, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)

    assert policy.observe(Observation("fridge", "cycle_duration", 1.6, 0.8, now)) is None
    assert policy.observe(Observation("fridge", "cycle_duration", 1.7, 0.8, now + timedelta(hours=1))) is None
    alert = policy.observe(Observation("fridge", "cycle_duration", 1.8, 0.8, now + timedelta(hours=2)))

    assert alert is not None
    assert alert.repeated_count == 3
    assert "changed from its learned baseline" in alert.message


def test_policy_blocks_low_confidence_baseline() -> None:
    policy = ConservativeAlertPolicy(min_repeated=2, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)

    assert policy.observe(Observation("fridge", "reactive_power", 2.0, 0.2, now)) is None
    assert policy.observe(Observation("fridge", "reactive_power", 2.2, 0.2, now + timedelta(hours=1))) is None
```

- [ ] **Step 2: Run alerting tests to verify they fail**

Run:

```bash
python -m pytest tests/test_alerting.py -q
```

Expected: FAIL with an import error for `alerting`.

- [ ] **Step 3: Implement alert policy**

Create `custom_components/circuitsetup_energy_analyzer/alerting.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import AlertEvidence, Severity


@dataclass(frozen=True, slots=True)
class Observation:
    """One anomaly observation before alert gating."""

    circuit_id: str
    feature: str
    score: float
    baseline_confidence: float
    observed_at: datetime
    observed_value: float = 0.0
    baseline_value: float = 0.0


class ConservativeAlertPolicy:
    """Require learning confidence and repeated evidence before alerting."""

    def __init__(
        self,
        *,
        min_repeated: int = 3,
        min_score: float = 3.0,
        min_baseline_confidence: float = 0.6,
    ) -> None:
        self._min_repeated = min_repeated
        self._min_score = min_score
        self._min_baseline_confidence = min_baseline_confidence
        self._observations: dict[tuple[str, str], list[Observation]] = {}

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Record an observation and return alert evidence if it passes gates."""
        if observation.baseline_confidence < self._min_baseline_confidence:
            return None
        if observation.score < self._min_score:
            return None

        key = (observation.circuit_id, observation.feature)
        observations = self._observations.setdefault(key, [])
        observations.append(observation)
        del observations[:-self._min_repeated]

        if len(observations) < self._min_repeated:
            return None

        first = observations[0]
        last = observations[-1]
        return AlertEvidence(
            circuit_id=observation.circuit_id,
            feature=observation.feature,
            severity=Severity.WARNING,
            message=(
                f"{observation.feature.replace('_', ' ')} changed from its learned "
                f"baseline across {len(observations)} recent observations."
            ),
            observed_value=last.observed_value,
            baseline_value=last.baseline_value,
            change_ratio=last.score,
            repeated_count=len(observations),
            first_seen=first.observed_at,
            last_seen=last.observed_at,
        )
```

- [ ] **Step 4: Run alerting tests**

Run:

```bash
python -m pytest tests/test_alerting.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit alert policy**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/alerting.py tests/test_alerting.py
git commit -m "feat: add conservative alert policy"
```

### Task 10: Integration Feature Store

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing store tests**

Create `tests/test_storage.py`:

```python
from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import CircuitEvent, EventType, RetentionMode
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData, prune_events


def test_prune_events_uses_retention_mode() -> None:
    now = datetime(2026, 6, 2, tzinfo=UTC)
    old = CircuitEvent("fridge", EventType.START, now - timedelta(days=45))
    recent = CircuitEvent("fridge", EventType.START, now - timedelta(days=5))
    data = FeatureStoreData(events=[old, recent], baselines={}, alerts=[])

    pruned = prune_events(data, RetentionMode.LIGHTWEIGHT, now)

    assert pruned.events == [recent]


def test_standard_retention_keeps_month_of_events() -> None:
    now = datetime(2026, 6, 2, tzinfo=UTC)
    event = CircuitEvent("fridge", EventType.START, now - timedelta(days=25))
    data = FeatureStoreData(events=[event], baselines={}, alerts=[])

    pruned = prune_events(data, RetentionMode.STANDARD, now)

    assert pruned.events == [event]


def test_event_round_trip_serialization() -> None:
    now = datetime(2026, 6, 2, tzinfo=UTC)
    event = CircuitEvent(
        "fridge",
        EventType.START,
        now,
        features={"startup_power_w": 220.0},
        evidence=("startup changed",),
    )

    from custom_components.circuitsetup_energy_analyzer.storage import event_from_dict, event_to_dict

    assert event_from_dict(event_to_dict(event)) == event
```

- [ ] **Step 2: Run store tests to verify they fail**

Run:

```bash
python -m pytest tests/test_storage.py -q
```

Expected: FAIL with an import error for `storage`.

- [ ] **Step 3: Implement feature store data and retention pruning**

Create `custom_components/circuitsetup_energy_analyzer/storage.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import AlertEvidence, BaselineStats, CircuitEvent, EventType, RetentionMode

RETENTION_WINDOWS = {
    RetentionMode.LIGHTWEIGHT: timedelta(days=14),
    RetentionMode.STANDARD: timedelta(days=45),
    RetentionMode.DIAGNOSTIC: timedelta(days=180),
}


@dataclass(slots=True)
class FeatureStoreData:
    """In-memory feature store payload."""

    events: list[CircuitEvent]
    baselines: dict[str, BaselineStats]
    alerts: list[AlertEvidence]


def event_to_dict(event: CircuitEvent) -> dict[str, Any]:
    """Serialize a circuit event for JSON storage."""
    return {
        "circuit_id": event.circuit_id,
        "event_type": event.event_type.value,
        "started_at": event.started_at.isoformat(),
        "ended_at": event.ended_at.isoformat() if event.ended_at else None,
        "features": event.features,
        "evidence": list(event.evidence),
    }


def event_from_dict(raw: dict[str, Any]) -> CircuitEvent:
    """Deserialize a circuit event from JSON storage."""
    ended_at = raw.get("ended_at")
    return CircuitEvent(
        circuit_id=raw["circuit_id"],
        event_type=EventType(raw["event_type"]),
        started_at=datetime.fromisoformat(raw["started_at"]),
        ended_at=datetime.fromisoformat(ended_at) if ended_at else None,
        features={key: float(value) for key, value in raw.get("features", {}).items()},
        evidence=tuple(str(value) for value in raw.get("evidence", [])),
    )


def prune_events(
    data: FeatureStoreData,
    retention_mode: RetentionMode,
    now: datetime,
) -> FeatureStoreData:
    """Return data with events pruned according to retention mode."""
    cutoff = now - RETENTION_WINDOWS[retention_mode]
    return FeatureStoreData(
        events=[event for event in data.events if event.started_at >= cutoff],
        baselines=data.baselines,
        alerts=data.alerts,
    )


class FeatureStore:
    """Home Assistant Store wrapper for compact analyzer data."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry_id}",
        )
        self.data = FeatureStoreData(events=[], baselines={}, alerts=[])

    async def async_load(self) -> None:
        """Load stored data."""
        raw = await self._store.async_load()
        if raw is None:
            self.data = FeatureStoreData(events=[], baselines={}, alerts=[])
            return
        self.data = FeatureStoreData(
            events=[event_from_dict(event) for event in raw.get("events", [])],
            baselines={},
            alerts=[],
        )

    async def async_save(self) -> None:
        """Persist stored data."""
        await self._store.async_save(
            {
                "events": [event_to_dict(event) for event in self.data.events],
                "baselines": {
                    key: asdict(value) for key, value in self.data.baselines.items()
                },
                "alerts": [asdict(alert) for alert in self.data.alerts],
            }
        )
```

- [ ] **Step 4: Run store tests**

Run:

```bash
python -m pytest tests/test_storage.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit feature store**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/storage.py tests/test_storage.py
git commit -m "feat: add analyzer feature store"
```

### Task 11: Runtime Coordinator

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Create: `tests/test_coordinator.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/__init__.py`

- [ ] **Step 1: Write failing coordinator tests**

Create `tests/test_coordinator.py`:

```python
from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState, process_events_into_state
from custom_components.circuitsetup_energy_analyzer.models import AlertEvidence, CircuitEvent, EventType, Severity


def test_process_events_updates_state() -> None:
    state = AnalyzerState()
    event = CircuitEvent(
        circuit_id="fridge",
        event_type=EventType.START,
        started_at=datetime(2026, 6, 2, tzinfo=UTC),
        features={"startup_power_w": 220.0},
    )

    result = process_events_into_state(state, [event], [])

    assert result.last_event_by_circuit["fridge"] is event
    assert result.anomaly_score_by_circuit["fridge"] == 0.0


def test_process_alerts_updates_anomaly_score() -> None:
    state = AnalyzerState()
    alert = AlertEvidence(
        circuit_id="fridge",
        feature="cycle_duration",
        severity=Severity.WARNING,
        message="cycle duration changed from its learned baseline across 3 recent observations.",
        observed_value=120.0,
        baseline_value=80.0,
        change_ratio=4.0,
        repeated_count=3,
        first_seen=datetime(2026, 6, 2, tzinfo=UTC),
        last_seen=datetime(2026, 6, 2, tzinfo=UTC),
    )

    result = process_events_into_state(state, [], [alert])

    assert result.active_alerts_by_circuit["fridge"] == [alert]
    assert result.anomaly_score_by_circuit["fridge"] == 4.0
```

- [ ] **Step 2: Run coordinator tests to verify they fail**

Run:

```bash
python -m pytest tests/test_coordinator.py -q
```

Expected: FAIL with an import error for `coordinator`.

- [ ] **Step 3: Implement coordinator state and HA runtime shell**

Create `custom_components/circuitsetup_energy_analyzer/coordinator.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .models import AlertEvidence, CircuitEvent


@dataclass(slots=True)
class AnalyzerState:
    """Runtime data exposed to diagnostic entities."""

    last_event_by_circuit: dict[str, CircuitEvent] = field(default_factory=dict)
    active_alerts_by_circuit: dict[str, list[AlertEvidence]] = field(default_factory=dict)
    anomaly_score_by_circuit: dict[str, float] = field(default_factory=dict)
    learning_by_circuit: dict[str, bool] = field(default_factory=dict)
    data_quality_by_circuit: dict[str, str] = field(default_factory=dict)


def process_events_into_state(
    state: AnalyzerState,
    events: list[CircuitEvent],
    alerts: list[AlertEvidence],
) -> AnalyzerState:
    """Return updated analyzer state for entities."""
    for event in events:
        state.last_event_by_circuit[event.circuit_id] = event
        state.anomaly_score_by_circuit.setdefault(event.circuit_id, 0.0)
    for alert in alerts:
        state.active_alerts_by_circuit.setdefault(alert.circuit_id, []).append(alert)
        state.anomaly_score_by_circuit[alert.circuit_id] = max(
            state.anomaly_score_by_circuit.get(alert.circuit_id, 0.0),
            alert.change_ratio,
        )
    return state


class EnergyAnalyzerCoordinator(DataUpdateCoordinator[AnalyzerState]):
    """Event-driven coordinator for source sensor changes."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=f"{DOMAIN}_{entry_id}",
            update_interval=None,
        )
        self.data = AnalyzerState()
        self._unsub_state_changes: Callable[[], None] | None = None

    async def async_start(self, source_entity_ids: list[str]) -> None:
        """Start listening to selected source sensors."""
        if self._unsub_state_changes is not None:
            self._unsub_state_changes()
        self._unsub_state_changes = async_track_state_change_event(
            self.hass,
            source_entity_ids,
            self._async_source_state_changed,
        )

    async def async_stop(self) -> None:
        """Stop listening to source sensors."""
        if self._unsub_state_changes is not None:
            self._unsub_state_changes()
            self._unsub_state_changes = None

    @callback
    def _async_source_state_changed(
        self,
        event: Event[EventStateChangedData],
    ) -> None:
        """Handle a HA source sensor state change."""
        if self.data is None:
            self.data = AnalyzerState()
        self.async_set_updated_data(self.data)
```

- [ ] **Step 4: Register coordinator in setup/unload**

Modify `custom_components/circuitsetup_energy_analyzer/__init__.py` to:

```python
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SOURCE_ENTITIES, DOMAIN, PLATFORMS
from .coordinator import EnergyAnalyzerCoordinator

type CircuitSetupEnergyAnalyzerConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Set up CircuitSetup Energy Analyzer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = EnergyAnalyzerCoordinator(hass, entry.entry_id)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_start(entry.data.get(CONF_SOURCE_ENTITIES, []))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Unload CircuitSetup Energy Analyzer."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_stop()
    return unload_ok
```

- [ ] **Step 5: Run coordinator tests**

Run:

```bash
python -m pytest tests/test_coordinator.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit coordinator**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/__init__.py custom_components/circuitsetup_energy_analyzer/coordinator.py tests/test_coordinator.py
git commit -m "feat: add event driven analyzer coordinator"
```

### Task 12: Diagnostic Entities

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/entity.py`
- Create: `custom_components/circuitsetup_energy_analyzer/sensor.py`
- Create: `custom_components/circuitsetup_energy_analyzer/binary_sensor.py`
- Create: `tests/test_entities.py`

- [ ] **Step 1: Write failing entity tests**

Create `tests/test_entities.py`:

```python
from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import CircuitEvent, EventType
from custom_components.circuitsetup_energy_analyzer.sensor import anomaly_score_value, last_event_value
from custom_components.circuitsetup_energy_analyzer.binary_sensor import is_learning, has_data_quality_problem


def test_sensor_values_read_coordinator_state() -> None:
    state = AnalyzerState()
    state.anomaly_score_by_circuit["fridge"] = 4.2
    state.last_event_by_circuit["fridge"] = CircuitEvent(
        circuit_id="fridge",
        event_type=EventType.START,
        started_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    assert anomaly_score_value(state, "fridge") == 4.2
    assert last_event_value(state, "fridge") == "start"


def test_binary_values_read_coordinator_state() -> None:
    state = AnalyzerState()
    state.learning_by_circuit["fridge"] = True
    state.data_quality_by_circuit["fridge"] = "missing_required_sensor"

    assert is_learning(state, "fridge")
    assert has_data_quality_problem(state, "fridge")
```

- [ ] **Step 2: Run entity tests to verify they fail**

Run:

```bash
python -m pytest tests/test_entities.py -q
```

Expected: FAIL with import errors for `sensor` or `binary_sensor`.

- [ ] **Step 3: Implement shared entity base**

Create `custom_components/circuitsetup_energy_analyzer/entity.py`:

```python
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AnalyzerState, EnergyAnalyzerCoordinator


class CircuitAnalyzerEntity(CoordinatorEntity[EnergyAnalyzerCoordinator]):
    """Base entity for one configured circuit."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EnergyAnalyzerCoordinator,
        circuit_id: str,
        circuit_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._circuit_id = circuit_id
        self._circuit_name = circuit_name

    @property
    def analyzer_state(self) -> AnalyzerState:
        """Return current analyzer state."""
        return self.coordinator.data or AnalyzerState()
```

- [ ] **Step 4: Implement sensor entities**

Create `custom_components/circuitsetup_energy_analyzer/sensor.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CIRCUITS, DOMAIN
from .coordinator import AnalyzerState, EnergyAnalyzerCoordinator
from .entity import CircuitAnalyzerEntity


def anomaly_score_value(state: AnalyzerState, circuit_id: str) -> float:
    """Return current anomaly score."""
    return state.anomaly_score_by_circuit.get(circuit_id, 0.0)


def last_event_value(state: AnalyzerState, circuit_id: str) -> str | None:
    """Return last event type."""
    event = state.last_event_by_circuit.get(circuit_id)
    return event.event_type.value if event else None


@dataclass(frozen=True, kw_only=True)
class CircuitSensorEntityDescription(SensorEntityDescription):
    """Sensor description for analyzer diagnostics."""

    value_fn: Callable[[AnalyzerState, str], str | float | None]


SENSOR_DESCRIPTIONS: tuple[CircuitSensorEntityDescription, ...] = (
    CircuitSensorEntityDescription(
        key="anomaly_score",
        translation_key="anomaly_score",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=anomaly_score_value,
    ),
    CircuitSensorEntityDescription(
        key="last_event",
        translation_key="last_event",
        value_fn=last_event_value,
    ),
)


class CircuitAnalyzerSensor(CircuitAnalyzerEntity, SensorEntity):
    """Analyzer diagnostic sensor."""

    entity_description: CircuitSensorEntityDescription

    def __init__(
        self,
        coordinator: EnergyAnalyzerCoordinator,
        circuit_id: str,
        circuit_name: str,
        description: CircuitSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, circuit_id, circuit_name)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.name}_{circuit_id}_{description.key}"
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> str | float | None:
        """Return native sensor value."""
        return self.entity_description.value_fn(self.analyzer_state, self._circuit_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up analyzer sensors."""
    coordinator: EnergyAnalyzerCoordinator = hass.data[DOMAIN][entry.entry_id]
    circuits = entry.data.get(CONF_CIRCUITS, [])
    entities = [
        CircuitAnalyzerSensor(coordinator, circuit["id"], circuit["name"], description)
        for circuit in circuits
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)
```

- [ ] **Step 5: Implement binary sensor entities**

Create `custom_components/circuitsetup_energy_analyzer/binary_sensor.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CIRCUITS, DOMAIN
from .coordinator import AnalyzerState, EnergyAnalyzerCoordinator
from .entity import CircuitAnalyzerEntity


def is_learning(state: AnalyzerState, circuit_id: str) -> bool:
    """Return whether a circuit is still learning."""
    return state.learning_by_circuit.get(circuit_id, True)


def has_data_quality_problem(state: AnalyzerState, circuit_id: str) -> bool:
    """Return whether a circuit has a data-quality problem."""
    return bool(state.data_quality_by_circuit.get(circuit_id))


@dataclass(frozen=True, kw_only=True)
class CircuitBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor description for analyzer diagnostics."""

    value_fn: Callable[[AnalyzerState, str], bool]


BINARY_SENSOR_DESCRIPTIONS: tuple[CircuitBinarySensorEntityDescription, ...] = (
    CircuitBinarySensorEntityDescription(
        key="learning",
        translation_key="learning",
        value_fn=is_learning,
    ),
    CircuitBinarySensorEntityDescription(
        key="data_quality_problem",
        translation_key="data_quality_problem",
        value_fn=has_data_quality_problem,
    ),
)


class CircuitAnalyzerBinarySensor(CircuitAnalyzerEntity, BinarySensorEntity):
    """Analyzer diagnostic binary sensor."""

    entity_description: CircuitBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: EnergyAnalyzerCoordinator,
        circuit_id: str,
        circuit_name: str,
        description: CircuitBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, circuit_id, circuit_name)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.name}_{circuit_id}_{description.key}"
        self._attr_translation_key = description.translation_key

    @property
    def is_on(self) -> bool:
        """Return binary sensor state."""
        return self.entity_description.value_fn(self.analyzer_state, self._circuit_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up analyzer binary sensors."""
    coordinator: EnergyAnalyzerCoordinator = hass.data[DOMAIN][entry.entry_id]
    circuits = entry.data.get(CONF_CIRCUITS, [])
    entities = [
        CircuitAnalyzerBinarySensor(coordinator, circuit["id"], circuit["name"], description)
        for circuit in circuits
        for description in BINARY_SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)
```

- [ ] **Step 6: Run entity tests**

Run:

```bash
python -m pytest tests/test_entities.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit entities**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/entity.py custom_components/circuitsetup_energy_analyzer/sensor.py custom_components/circuitsetup_energy_analyzer/binary_sensor.py tests/test_entities.py
git commit -m "feat: expose analyzer diagnostic entities"
```

### Task 13: Config Flow And Options Flow

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/config_flow.py`
- Create: `custom_components/circuitsetup_energy_analyzer/strings.json`
- Create: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing config flow tests**

Create `tests/test_config_flow.py`:

```python
from homeassistant import config_entries

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS, CONF_SOURCE_ENTITIES, DOMAIN
from custom_components.circuitsetup_energy_analyzer.config_flow import format_mapping_suggestions
from custom_components.circuitsetup_energy_analyzer.discovery import DiscoveredSensor
from custom_components.circuitsetup_energy_analyzer.mapping import DualPhaseSuggestion
from custom_components.circuitsetup_energy_analyzer.models import SensorRole


async def test_user_flow_creates_entry(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={
            CONF_SOURCE_ENTITIES: ["sensor.fridge_power"],
            CONF_CIRCUITS: [
                {
                    "id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                }
            ],
        },
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "CircuitSetup Energy Analyzer"
    assert result["data"][CONF_SOURCE_ENTITIES] == ["sensor.fridge_power"]


async def test_user_flow_requires_source_entities(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_SOURCE_ENTITIES: [], CONF_CIRCUITS: []},
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "no_source_entities"


def test_format_mapping_suggestions_shows_confirmation_text() -> None:
    left = DiscoveredSensor(
        "sensor.panel_ch1_power",
        "HVAC L1 Power",
        SensorRole.REAL_POWER,
        "meter-1",
        "W",
        "power",
        "esphome",
    )
    right = DiscoveredSensor(
        "sensor.panel_ch2_power",
        "HVAC L2 Power",
        SensorRole.REAL_POWER,
        "meter-1",
        "W",
        "power",
        "esphome",
    )

    text = format_mapping_suggestions(
        [DualPhaseSuggestion(left, right, 0.8, ("neighboring channels",))]
    )

    assert "HVAC L1 Power" in text
    assert "HVAC L2 Power" in text
    assert "confirm or manually override" in text
```

- [ ] **Step 2: Run config flow tests to verify they fail**

Run:

```bash
python -m pytest tests/test_config_flow.py -q
```

Expected: FAIL with an import error for `config_flow`.

- [ ] **Step 3: Implement config and options flow**

Create `custom_components/circuitsetup_energy_analyzer/config_flow.py`:

```python
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_CIRCUITS,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DOMAIN,
)
from .discovery import async_discover_sensors
from .mapping import DualPhaseSuggestion, suggest_dual_phase_pairs


def format_mapping_suggestions(suggestions: list[DualPhaseSuggestion]) -> str:
    """Format auto-suggested dual-phase mappings for user confirmation."""
    if not suggestions:
        return "No dual-phase channel suggestions were found. Manually define circuit channels."
    lines = [
        "Suggested dual-phase channel pairs. Review each suggestion, then confirm or manually override the circuit channels."
    ]
    for suggestion in suggestions[:5]:
        lines.append(
            f"- {suggestion.left.name} + {suggestion.right.name} "
            f"({suggestion.confidence:.0%}; {', '.join(suggestion.reasons)})"
        )
    return "\n".join(lines)


DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SOURCE_ENTITIES): [str],
        vol.Required(CONF_CIRCUITS): [dict],
        vol.Optional(CONF_SENSITIVITY, default=DEFAULT_SENSITIVITY): str,
        vol.Optional(CONF_RETENTION_MODE, default=DEFAULT_RETENTION_MODE): str,
    }
)


class CircuitSetupEnergyAnalyzerConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Config flow for CircuitSetup Energy Analyzer."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CircuitSetupEnergyAnalyzerOptionsFlow:
        """Create the options flow."""
        return CircuitSetupEnergyAnalyzerOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle user setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            source_entities = user_input.get(CONF_SOURCE_ENTITIES, [])
            if not source_entities:
                errors["base"] = "no_source_entities"
            else:
                return self.async_create_entry(
                    title="CircuitSetup Energy Analyzer",
                    data=dict(user_input),
                )

        discovered = async_discover_sensors(self.hass)
        suggestions = suggest_dual_phase_pairs(discovered)

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "mapping_suggestions": format_mapping_suggestions(suggestions)
            },
        )


class CircuitSetupEnergyAnalyzerOptionsFlow(config_entries.OptionsFlow):
    """Options flow for CircuitSetup Energy Analyzer."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=dict(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SENSITIVITY,
                        default=self._config_entry.options.get(
                            CONF_SENSITIVITY,
                            self._config_entry.data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
                        ),
                    ): str,
                    vol.Optional(
                        CONF_RETENTION_MODE,
                        default=self._config_entry.options.get(
                            CONF_RETENTION_MODE,
                            self._config_entry.data.get(
                                CONF_RETENTION_MODE,
                                DEFAULT_RETENTION_MODE,
                            ),
                        ),
                    ): str,
                }
            ),
        )
```

- [ ] **Step 4: Add translations**

Create `custom_components/circuitsetup_energy_analyzer/strings.json`:

```json
{
  "title": "CircuitSetup Energy Analyzer",
  "config": {
    "step": {
      "user": {
        "title": "Configure CircuitSetup Energy Analyzer",
        "description": "Select ESPHome ATM90E32 source sensors and define monitored circuits.\n\n{mapping_suggestions}",
        "data": {
          "source_entities": "Source sensor entity IDs",
          "circuits": "Circuit definitions",
          "sensitivity": "Sensitivity",
          "retention_mode": "Retention mode"
        }
      }
    },
    "error": {
      "no_source_entities": "Select at least one source sensor."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "CircuitSetup Energy Analyzer options",
        "data": {
          "sensitivity": "Sensitivity",
          "retention_mode": "Retention mode"
        }
      }
    }
  },
  "entity": {
    "sensor": {
      "anomaly_score": {
        "name": "Anomaly score"
      },
      "last_event": {
        "name": "Last event"
      }
    },
    "binary_sensor": {
      "learning": {
        "name": "Learning"
      },
      "data_quality_problem": {
        "name": "Data quality problem"
      }
    }
  }
}
```

- [ ] **Step 5: Run config flow tests**

Run:

```bash
python -m pytest tests/test_config_flow.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit config flow**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/config_flow.py custom_components/circuitsetup_energy_analyzer/strings.json tests/test_config_flow.py
git commit -m "feat: add setup and options flow"
```

### Task 14: Notifications, Repairs, And Services

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/notifications.py`
- Create: `custom_components/circuitsetup_energy_analyzer/repairs.py`
- Create: `custom_components/circuitsetup_energy_analyzer/services.py`
- Create: `custom_components/circuitsetup_energy_analyzer/services.yaml`
- Create: `tests/test_services.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/__init__.py`

- [ ] **Step 1: Write failing service helper tests**

Create `tests/test_services.py`:

```python
from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.models import AlertEvidence, Severity
from custom_components.circuitsetup_energy_analyzer.notifications import notification_id_for_alert
from custom_components.circuitsetup_energy_analyzer.repairs import issue_id_for_circuit_problem


def test_notification_id_is_stable_per_circuit_feature() -> None:
    alert = AlertEvidence(
        circuit_id="fridge",
        feature="cycle_duration",
        severity=Severity.WARNING,
        message="cycle duration changed from its learned baseline across 3 recent observations.",
        observed_value=120.0,
        baseline_value=80.0,
        change_ratio=4.0,
        repeated_count=3,
        first_seen=datetime(2026, 6, 2, tzinfo=UTC),
        last_seen=datetime(2026, 6, 2, tzinfo=UTC),
    )

    assert notification_id_for_alert(alert) == "circuitsetup_energy_analyzer_fridge_cycle_duration"


def test_repair_issue_id_is_stable() -> None:
    assert issue_id_for_circuit_problem("hvac", "phase_mismatch") == "hvac_phase_mismatch"
```

- [ ] **Step 2: Run service tests to verify they fail**

Run:

```bash
python -m pytest tests/test_services.py -q
```

Expected: FAIL with import errors for `notifications` and `repairs`.

- [ ] **Step 3: Implement persistent notification helper**

Create `custom_components/circuitsetup_energy_analyzer/notifications.py`:

```python
from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .models import AlertEvidence


def notification_id_for_alert(alert: AlertEvidence) -> str:
    """Return stable notification id for an alert."""
    return f"{DOMAIN}_{alert.circuit_id}_{alert.feature}"


async def async_create_alert_notification(
    hass: HomeAssistant,
    alert: AlertEvidence,
) -> None:
    """Create a persistent notification for important analyzer evidence."""
    persistent_notification.async_create(
        hass,
        message=alert.message,
        title=f"CircuitSetup Energy Analyzer: {alert.circuit_id}",
        notification_id=notification_id_for_alert(alert),
    )
```

- [ ] **Step 4: Implement Repairs helper**

Create `custom_components/circuitsetup_energy_analyzer/repairs.py`:

```python
from __future__ import annotations

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def issue_id_for_circuit_problem(circuit_id: str, problem: str) -> str:
    """Return stable Repairs issue id."""
    return f"{circuit_id}_{problem}"


def async_create_data_quality_issue(
    hass: HomeAssistant,
    circuit_id: str,
    problem: str,
    severity: ir.IssueSeverity = ir.IssueSeverity.WARNING,
) -> None:
    """Create a data-quality Repairs issue."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id_for_circuit_problem(circuit_id, problem),
        is_fixable=True,
        severity=severity,
        translation_key=problem,
        data={"circuit_id": circuit_id},
    )


class ConfirmDataQualityRepairFlow(RepairsFlow):
    """Confirm-only repair flow for data-quality issues."""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Start repair flow."""
        return await self.async_step_confirm(user_input)

    async def async_step_confirm(
        self,
        user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Confirm repair flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create repair flow."""
    return ConfirmDataQualityRepairFlow()
```

- [ ] **Step 5: Implement service registration**

Create `custom_components/circuitsetup_energy_analyzer/services.py`:

```python
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

SERVICE_RELEARN_BASELINE = "relearn_baseline"
SERVICE_PAUSE_ALERTS = "pause_alerts"
SERVICE_ACKNOWLEDGE_ALERT = "acknowledge_alert"
SERVICE_EXPORT_DIAGNOSTICS = "export_diagnostics"
SERVICE_RUN_MAPPING_CHECKS = "run_mapping_checks"

CIRCUIT_SERVICE_SCHEMA = vol.Schema({vol.Required("circuit_id"): cv.string})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def _handle_circuit_service(call: ServiceCall) -> None:
        circuit_id = call.data["circuit_id"]
        hass.bus.async_fire(
            f"{DOMAIN}_{call.service}",
            {"circuit_id": circuit_id},
        )

    for service in (
        SERVICE_RELEARN_BASELINE,
        SERVICE_PAUSE_ALERTS,
        SERVICE_ACKNOWLEDGE_ALERT,
        SERVICE_EXPORT_DIAGNOSTICS,
        SERVICE_RUN_MAPPING_CHECKS,
    ):
        hass.services.async_register(
            DOMAIN,
            service,
            _handle_circuit_service,
            schema=CIRCUIT_SERVICE_SCHEMA,
        )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unregister integration services."""
    for service in (
        SERVICE_RELEARN_BASELINE,
        SERVICE_PAUSE_ALERTS,
        SERVICE_ACKNOWLEDGE_ALERT,
        SERVICE_EXPORT_DIAGNOSTICS,
        SERVICE_RUN_MAPPING_CHECKS,
    ):
        hass.services.async_remove(DOMAIN, service)
```

Create `custom_components/circuitsetup_energy_analyzer/services.yaml`:

```yaml
relearn_baseline:
  fields:
    circuit_id:
      required: true
      selector:
        text:
pause_alerts:
  fields:
    circuit_id:
      required: true
      selector:
        text:
acknowledge_alert:
  fields:
    circuit_id:
      required: true
      selector:
        text:
export_diagnostics:
  fields:
    circuit_id:
      required: true
      selector:
        text:
run_mapping_checks:
  fields:
    circuit_id:
      required: true
      selector:
        text:
```

- [ ] **Step 6: Wire services into setup and unload**

Modify `custom_components/circuitsetup_energy_analyzer/__init__.py`:

```python
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SOURCE_ENTITIES, DOMAIN, PLATFORMS
from .coordinator import EnergyAnalyzerCoordinator
from .services import async_setup_services, async_unload_services

type CircuitSetupEnergyAnalyzerConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Set up CircuitSetup Energy Analyzer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN]:
        await async_setup_services(hass)
    coordinator = EnergyAnalyzerCoordinator(hass, entry.entry_id)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_start(entry.data.get(CONF_SOURCE_ENTITIES, []))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Unload CircuitSetup Energy Analyzer."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_stop()
        if not hass.data.get(DOMAIN):
            await async_unload_services(hass)
    return unload_ok
```

- [ ] **Step 7: Run service tests**

Run:

```bash
python -m pytest tests/test_services.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit notifications, repairs, and services**

Run:

```bash
git add custom_components/circuitsetup_energy_analyzer/__init__.py custom_components/circuitsetup_energy_analyzer/notifications.py custom_components/circuitsetup_energy_analyzer/repairs.py custom_components/circuitsetup_energy_analyzer/services.py custom_components/circuitsetup_energy_analyzer/services.yaml tests/test_services.py
git commit -m "feat: add alert notifications repairs and services"
```

### Task 15: Diagnostics And Documentation

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/diagnostics.py`
- Create: `docs/dashboard-example.yaml`
- Modify: `README.md`
- Modify: `custom_components/circuitsetup_energy_analyzer/strings.json`

- [ ] **Step 1: Add diagnostics export**

Create `custom_components/circuitsetup_energy_analyzer/diagnostics.py`:

```python
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import async_entries_for_config_entry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    device_registry = async_get_device_registry(hass)
    devices = async_entries_for_config_entry(device_registry, entry.entry_id)
    return {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data_keys": sorted(entry.data),
            "option_keys": sorted(entry.options),
        },
        "devices": [
            {
                "id": device.id,
                "name": device.name,
                "manufacturer": device.manufacturer,
                "model": device.model,
            }
            for device in devices
        ],
        "runtime_loaded": entry.entry_id in hass.data.get(DOMAIN, {}),
    }
```

- [ ] **Step 2: Add dashboard example**

Create `docs/dashboard-example.yaml`:

```yaml
type: sections
title: Energy Analyzer
sections:
  - type: grid
    cards:
      - type: entities
        title: Refrigerator
        entities:
          - entity: sensor.fridge_energy_analyzer_anomaly_score
          - entity: sensor.fridge_energy_analyzer_last_event
          - entity: binary_sensor.fridge_energy_analyzer_learning
          - entity: binary_sensor.fridge_energy_analyzer_data_quality_problem
      - type: entities
        title: HVAC
        entities:
          - entity: sensor.hvac_energy_analyzer_anomaly_score
          - entity: sensor.hvac_energy_analyzer_last_event
          - entity: binary_sensor.hvac_energy_analyzer_learning
          - entity: binary_sensor.hvac_energy_analyzer_data_quality_problem
```

- [ ] **Step 3: Expand README with HACS and behavior notes**

Replace `README.md` with:

```markdown
# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration for analyzing CircuitSetup 6 Channel Energy Meter data exposed by ESPHome ATM90E32 sensors.

The integration learns conservative per-circuit baselines for single-phase appliances, dual-phase appliances, and mixed or unprofiled circuits. It exposes diagnostic entities, persistent notifications for important events, and Repairs for integration or source-data problems.

## Installation

Install through HACS as a custom repository:

1. Add this repository as a HACS custom integration repository.
2. Install CircuitSetup Energy Analyzer.
3. Restart Home Assistant.
4. Add the integration from Settings > Devices & services.

## Circuit Modes

- Single-phase appliance: one CT/channel mapped to one primary appliance.
- Dual-phase appliance: two CT/channels treated as one appliance, with leg imbalance checks.
- Mixed or unprofiled circuit: no appliance-health diagnosis; feed-quality and large-change diagnostics only.

## Alert Philosophy

The integration is evidence-first. It learns for at least 7 days or enough profile-specific cycles, requires repeated anomaly evidence, and phrases alerts as possible behavior changes rather than appliance diagnoses.

## Dashboard

Version 1 uses standard Home Assistant entities. See `docs/dashboard-example.yaml` for a starting point.
```

- [ ] **Step 4: Add Repair translations**

Modify `custom_components/circuitsetup_energy_analyzer/strings.json` by adding this top-level `issues` section before the final closing brace:

```json
  ,
  "issues": {
    "missing_required_sensor": {
      "title": "Energy Analyzer source sensor is missing",
      "description": "A configured circuit is missing a required source sensor. Reconfigure the circuit mapping before appliance analysis can continue."
    },
    "phase_mismatch": {
      "title": "Energy Analyzer phase pairing looks suspicious",
      "description": "A dual-phase circuit has source data that does not look like a valid paired load. Review the selected channels and CT orientation."
    },
    "stale_source_sensor": {
      "title": "Energy Analyzer source sensor is stale",
      "description": "A configured source sensor has not updated recently. Appliance analysis is paused for the affected circuit."
    }
  }
```

After editing, the file must remain valid JSON. The final structure should contain `title`, `config`, `options`, `entity`, and `issues` at the top level.

- [ ] **Step 5: Run docs-related import checks**

Run:

```bash
python -m pytest tests/test_services.py tests/test_entities.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit diagnostics and docs**

Run:

```bash
git add README.md docs/dashboard-example.yaml custom_components/circuitsetup_energy_analyzer/diagnostics.py custom_components/circuitsetup_energy_analyzer/strings.json
git commit -m "docs: document energy analyzer setup and diagnostics"
```

### Task 16: Final Validation

**Files:**
- Modify only files required to fix validation failures.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run static lint if dependencies are installed**

Run:

```bash
python -m ruff check .
```

Expected: PASS.

If `ruff` is not installed, run:

```bash
python -m pip install -e ".[test]" ruff
python -m ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run HACS layout sanity check**

Run:

```bash
@'
from pathlib import Path
import json

root = Path(".")
integration = root / "custom_components" / "circuitsetup_energy_analyzer"
assert (root / "hacs.json").exists()
assert (integration / "manifest.json").exists()
manifest = json.loads((integration / "manifest.json").read_text())
assert manifest["domain"] == "circuitsetup_energy_analyzer"
assert manifest["config_flow"] is True
assert manifest["version"]
assert len(list((root / "custom_components").iterdir())) == 1
print("hacs layout ok")
'@ | python -
```

Expected: prints `hacs layout ok`.

- [ ] **Step 4: Run Home Assistant manifest sanity check**

Run:

```bash
@'
import json
from pathlib import Path

manifest = json.loads(Path("custom_components/circuitsetup_energy_analyzer/manifest.json").read_text())
required = {"domain", "name", "documentation", "issue_tracker", "codeowners", "config_flow", "version"}
missing = required - set(manifest)
assert not missing, missing
assert manifest["iot_class"] == "local_push"
print("manifest ok")
'@ | python -
```

Expected: prints `manifest ok`.

- [ ] **Step 5: Commit validation fixes**

If any validation fixes were required, run:

```bash
git add custom_components tests docs README.md pyproject.toml hacs.json
git commit -m "fix: resolve validation issues"
```

If no files changed, skip this commit.

## Plan Self-Review

Spec coverage:

- HACS-installable custom integration: Tasks 1, 13, 15, 16.
- Circuit modes and manual/auto channel mapping: Tasks 2, 3, 4, 13.
- Single-phase and dual-phase analysis: Tasks 5, 6, 7, 8.
- Appliance profiles: Task 2.
- Baseline learning and conservative alerts: Tasks 8 and 9.
- Derived event/feature storage: Task 10.
- Diagnostic entities and binary sensors: Task 12.
- Persistent notifications, Repairs, and services: Task 14.
- Standard HA entities first, dashboard example later: Tasks 12 and 15.
- Tests and validation: Every task includes tests; Task 16 runs full validation.

No unresolved scope remains for v1. Full NILM, custom Lovelace cards, external databases, waveform/harmonic analysis, and ESPHome firmware changes remain outside this plan.
