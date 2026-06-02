from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class ApplianceProfile(StrEnum):
    """Supported appliance analysis profiles."""

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
    MAINS_NILM = "mains_nilm"
    MOTOR_LOAD = "motor_load"
    RESISTIVE_LOAD = "resistive_load"
    MIXED = "mixed"


class CircuitMode(StrEnum):
    """Circuit topology used for appliance analysis."""

    SINGLE_PHASE = "single_phase"
    DUAL_PHASE = "dual_phase"
    MIXED = "mixed"
    MAINS_NILM = "mains_nilm"


class RetentionMode(StrEnum):
    """Evidence retention depth."""

    LIGHTWEIGHT = "lightweight"
    STANDARD = "standard"
    DIAGNOSTIC = "diagnostic"


class SensorRole(StrEnum):
    """Role assigned to a source sensor."""

    VOLTAGE = "voltage"
    CURRENT = "current"
    REAL_POWER = "real_power"
    REACTIVE_POWER = "reactive_power"
    APPARENT_POWER = "apparent_power"
    POWER_FACTOR = "power_factor"
    FREQUENCY = "frequency"
    ENERGY = "energy"


class EventType(StrEnum):
    """Classifier output event types."""

    START = "start"
    STOP = "stop"
    STEADY_WINDOW = "steady_window"
    VOLTAGE_SAG = "voltage_sag"
    VOLTAGE_SWELL = "voltage_swell"
    LEG_IMBALANCE = "leg_imbalance"
    DATA_QUALITY = "data_quality"


class Severity(StrEnum):
    """Alert and evidence severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SensorRef:
    """Configured source sensor and its analysis role."""

    entity_id: str
    role: SensorRole
    leg: str | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class CircuitConfig:
    """Configured circuit under analysis."""

    circuit_id: str
    name: str
    appliance_profile: ApplianceProfile
    mode: CircuitMode
    sensors: tuple[SensorRef, ...] = ()
    retention_mode: RetentionMode = RetentionMode.STANDARD


@dataclass(frozen=True, slots=True)
class CircuitSample:
    """Single-phase measurement sample."""

    timestamp: datetime
    circuit_id: str
    real_power: float | None = None
    current: float | None = None
    voltage: float | None = None
    reactive_power: float | None = None
    apparent_power: float | None = None
    power_factor: float | None = None
    frequency: float | None = None
    energy: float | None = None


@dataclass(frozen=True, slots=True)
class LegSample:
    """Measurement sample for one leg of a split-phase circuit."""

    leg: str
    real_power: float | None = None
    current: float | None = None
    voltage: float | None = None
    reactive_power: float | None = None
    apparent_power: float | None = None
    power_factor: float | None = None


@dataclass(frozen=True, slots=True)
class DualPhaseSample:
    """Dual-phase measurement sample."""

    timestamp: datetime
    circuit_id: str
    leg_a: LegSample
    leg_b: LegSample
    frequency: float | None = None
    energy: float | None = None


@dataclass(frozen=True, slots=True)
class CircuitEvent:
    """Detected appliance or circuit event."""

    timestamp: datetime
    circuit_id: str
    event_type: EventType
    severity: Severity = Severity.INFO
    features: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


@dataclass(frozen=True, slots=True)
class BaselineStats:
    """Robust learned baseline statistics for one feature."""

    feature: str
    sample_count: int
    median: float
    mad: float
    p10: float
    p90: float
    confidence: float


@dataclass(frozen=True, slots=True)
class AlertEvidence:
    """Evidence attached to a generated alert."""

    timestamp: datetime
    circuit_id: str
    severity: Severity
    message: str
    event_type: EventType | None = None
    features: dict[str, float] = field(default_factory=dict)
