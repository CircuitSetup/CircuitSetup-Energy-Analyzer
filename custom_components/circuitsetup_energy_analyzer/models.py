from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ApplianceProfile(StrEnum):
    """Supported appliance analysis profiles."""

    REFRIGERATOR = "refrigerator"
    FREEZER = "freezer"
    HVAC = "hvac"
    HVAC_COMPRESSOR = "hvac_compressor"
    HEAT_PUMP = "heat_pump"
    MINI_SPLIT = "mini_split"
    HVAC_BLOWER = "hvac_blower"
    ELECTRIC_HEAT = "electric_heat"
    WATER_HEATER = "water_heater"
    OVEN = "oven"
    MICROWAVE = "microwave"
    DISHWASHER = "dishwasher"
    THREE_D_PRINTER = "3d_printer"
    WASHER = "washer"
    DRYER = "dryer"
    POOL_PUMP = "pool_pump"
    WATER_PUMP = "water_pump"
    WELL_PUMP = "well_pump"
    SUMP_PUMP = "sump_pump"
    EV_CHARGER = "ev_charger"
    SOLAR_INVERTER = "solar_inverter"
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


class NilmSourceKind(StrEnum):
    """Explicit source topology supported by NILM processing."""

    MAINS = "mains"
    PURE_MIXED = "pure_mixed"
    PRIMARY_MIXED = "primary_mixed"


class PowerFlowMode(StrEnum):
    """Real-power sign convention for a circuit."""

    LOAD = "load"
    GENERATION = "generation"
    MAINS_NET = "mains_net"


class RetentionMode(StrEnum):
    """Evidence retention depth."""

    LIGHTWEIGHT = "lightweight"
    STANDARD = "standard"
    DIAGNOSTIC = "diagnostic"


class SensorRole(StrEnum):
    """Role assigned to a source sensor."""

    VOLTAGE = "voltage"
    CURRENT = "current"
    PEAK_CURRENT = "peak_current"
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
    POWER_TRANSITION = "power_transition"
    STEADY_WINDOW = "steady_window"
    VOLTAGE_SAG = "voltage_sag"
    VOLTAGE_SWELL = "voltage_swell"
    VOLTAGE_IMBALANCE = "voltage_imbalance"
    FREQUENCY_DROP = "frequency_drop"
    FREQUENCY_SPIKE = "frequency_spike"
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
    power_flow: PowerFlowMode = PowerFlowMode.LOAD
    nilm_detection_enabled: bool = False
    nilm_detection_sensitivity: str = "balanced"
    energy_usage_window_days: int = 7
    daily_energy_spike_ratio: float = 0.25
    daily_energy_goal_kwh: float | None = None
    energy_goal_alert_ratio: float = 1.0
    billing_cycle_start_day: int = 1
    billing_cycle_budget_kwh: float | None = None
    billing_cycle_budget_alert_ratio: float = 1.0
    billing_cycle_min_elapsed_days: int = 3
    cost_cycle_start_day: int = 1
    demand_window_minutes: int = 15
    demand_limit_w: float | None = None
    standby_window_hours: int = 48
    standby_threshold_w: float = 8.0
    always_on_alert_w: float | None = None
    standby_min_samples: int = 24


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
    features: Mapping[str, Any] = field(default_factory=dict)

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
    features: Mapping[str, Any] = field(default_factory=dict)
    feature: str = ""
    value_metric: str = ""
    observed_value: float = 0.0
    baseline_value: float = 0.0
    change_ratio: float = 0.0
    repeated_count: int = 1
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    feedback_status: str | None = None
    feedback_effect: str | None = None
    feedback_expires_at: datetime | None = None
    matching_feedback_fingerprint: str | None = None
    adjusted_min_repeated: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))
