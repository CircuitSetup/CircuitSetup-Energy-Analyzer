from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .balance import DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W
from .capacity import DEFAULT_CAPACITY_WARNING_RATIO
from .const import DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT
from .load_shift import FLEXIBLE_LOAD_RUNNING_THRESHOLD_W
from .mains_power_quality import (
    DEFAULT_FREQUENCY_DROP_HZ,
    DEFAULT_FREQUENCY_SPIKE_HZ,
    DEFAULT_VOLTAGE_IMBALANCE_RATIO,
    DEFAULT_VOLTAGE_SAG_RATIO,
    DEFAULT_VOLTAGE_SWELL_RATIO,
)
from .metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
)
from .phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from .solar_flow import (
    EXPORT_TOLERANCE_W,
    HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    SOLAR_SURPLUS_THRESHOLD_W,
)
from .standby import DEFAULT_STANDBY_THRESHOLD_W, DEFAULT_STANDBY_WINDOW_HOURS
from .usage import DEFAULT_DAILY_USAGE_SPIKE_RATIO
from .ux import friendly_feature_name

_SETTING_DEFAULTS: dict[str, Any] = {
    "daily_spike_ratio": DEFAULT_DAILY_USAGE_SPIKE_RATIO,
    "max_active_minutes": None,
    "max_idle_minutes": None,
    "warning_ratio": DEFAULT_CAPACITY_WARNING_RATIO,
    "window_hours": DEFAULT_STANDBY_WINDOW_HOURS,
    "standby_threshold_w": DEFAULT_STANDBY_THRESHOLD_W,
    "always_on_alert_w": 0.0,
    "standby_min_samples": 24,
    "leg_imbalance_warning_ratio": DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
    "leg_imbalance_min_total_power_w": DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    "mains_voltage_sag_ratio": DEFAULT_VOLTAGE_SAG_RATIO,
    "mains_voltage_swell_ratio": DEFAULT_VOLTAGE_SWELL_RATIO,
    "mains_frequency_drop_hz": DEFAULT_FREQUENCY_DROP_HZ,
    "mains_frequency_spike_hz": DEFAULT_FREQUENCY_SPIKE_HZ,
    "mains_voltage_imbalance_ratio": DEFAULT_VOLTAGE_IMBALANCE_RATIO,
    "apparent_power_tolerance_percent": (
        DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT
    ),
    "power_factor_tolerance": DEFAULT_POWER_FACTOR_TOLERANCE,
    "minimum_apparent_power_va": DEFAULT_MIN_APPARENT_POWER_VA,
    "balance_negative_tolerance_w": DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
    "export_tolerance_w": EXPORT_TOLERANCE_W,
    "solar_export_tolerance_w": EXPORT_TOLERANCE_W,
    "solar_surplus_threshold_w": SOLAR_SURPLUS_THRESHOLD_W,
    "high_solar_surplus_threshold_w": HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    "flexible_load_running_threshold_w": FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
    "linked_thermostat_entities": [],
    "thermostat_temperature_sensor_map": {},
    "blower_represents_gas_heat": False,
    "hvac_efficiency_change_threshold_pct": (
        DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT
    ),
}

_SETTING_EXPECTED_EFFECTS = {
    "daily_spike_ratio": (
        "Tune this setting toward the observed history without requiring manual "
        "threshold math."
    ),
    "operating_on_threshold_w": (
        "Turn Running on only after the appliance clears a stable start "
        "threshold."
    ),
    "operating_off_threshold_w": (
        "Keep brief power dips from ending a run while still turning Running "
        "off near true idle draw."
    ),
    "max_active_minutes": (
        "Reduce false long-run alerts while still flagging unusually long cycles."
    ),
    "max_idle_minutes": (
        "Reduce idle-runtime noise while keeping extended idle runs visible."
    ),
    "warning_ratio": (
        "Warn earlier when usage approaches capacity, without changing breaker "
        "or safety assumptions."
    ),
    "window_hours": (
        "Use enough standby history to distinguish normal idle draw from "
        "short-lived power changes."
    ),
    "standby_threshold_w": (
        "Separate normal standby draw from runs so idle alerts are less noisy."
    ),
    "always_on_alert_w": (
        "Surface unusually high Always On draw without changing run-cycle or "
        "standby detection."
    ),
    "standby_min_samples": (
        "Require enough standby samples before changing idle detection behavior."
    ),
    "leg_imbalance_warning_ratio": (
        "Tune split-phase imbalance alerts toward observed paired-leg behavior."
    ),
    "leg_imbalance_min_total_power_w": (
        "Avoid imbalance alerts when the circuit is below meaningful total load."
    ),
    "mains_voltage_sag_ratio": (
        "Tune mains voltage sag alerts toward observed voltage behavior."
    ),
    "mains_voltage_swell_ratio": (
        "Tune mains voltage spike alerts toward observed voltage behavior."
    ),
    "mains_frequency_drop_hz": (
        "Tune mains frequency drop alerts toward observed frequency behavior."
    ),
    "mains_frequency_spike_hz": (
        "Tune mains frequency spike alerts toward observed frequency behavior."
    ),
    "mains_voltage_imbalance_ratio": (
        "Tune mains leg-voltage mismatch alerts toward observed split-phase "
        "voltage behavior."
    ),
    "apparent_power_tolerance_percent": (
        "Tune metric consistency checks for W, VA, current, and power-factor "
        "relationships toward this circuit's observed sensor residuals."
    ),
    "power_factor_tolerance": (
        "Tune power-factor relationship checks to this circuit's observed "
        "sensor behavior without hiding larger metric mismatches."
    ),
    "minimum_apparent_power_va": (
        "Ignore low apparent-power samples where sensor noise can dominate "
        "metric consistency checks."
    ),
    "balance_negative_tolerance_w": (
        "Tune mains-minus-load balance checks while still surfacing mapping, "
        "solar, or CT-orientation problems."
    ),
    "export_tolerance_w": (
        "Keep normal CT and inverter timing drift from triggering solar-flow "
        "inconsistency guidance, while still surfacing larger export mismatches."
    ),
    "solar_export_tolerance_w": (
        "Keep normal CT and inverter timing drift from triggering solar-flow "
        "inconsistency guidance, while still surfacing larger export mismatches."
    ),
    "solar_surplus_threshold_w": (
        "Start solar surplus guidance near typical observed export so load "
        "shifting prompts are less noisy."
    ),
    "high_solar_surplus_threshold_w": (
        "Reserve high solar surplus guidance for the upper end of observed "
        "export events."
    ),
    "flexible_load_running_threshold_w": (
        "Classify flexible loads as running only after their draw clears the "
        "idle/noise floor, so load-shift prompts do not treat standby draw as "
        "active use."
    ),
    "linked_thermostat_entities": (
        "Associate this appliance with the thermostat zones its activity serves."
    ),
    "thermostat_temperature_sensor_map": (
        "Use the observed indoor sensor when it is a better temperature source "
        "than the thermostat's current-temperature attribute."
    ),
    "blower_represents_gas_heat": (
        "Measure this blower as the electrical proxy for gas heat while keeping "
        "cooling response attributed to the compressor."
    ),
    "hvac_efficiency_change_threshold_pct": (
        "Set how much slower weather-normalized runtime must be before an alert."
    ),
}

_SETTING_CONTROL_DESCRIPTIONS = {
    "daily_spike_ratio": (
        "Controls how far daily energy can drift above normal before high-usage "
        "guidance appears."
    ),
    "operating_on_threshold_w": (
        "Controls the power level that turns appliance activity on."
    ),
    "operating_off_threshold_w": (
        "Controls the power level that turns appliance activity back to idle."
    ),
    "max_active_minutes": (
        "Controls when a running cycle is considered unusually long."
    ),
    "max_idle_minutes": (
        "Controls when an idle-but-not-off appliance should be reviewed."
    ),
    "warning_ratio": (
        "Controls how close load can get to configured circuit capacity before "
        "capacity guidance appears."
    ),
    "window_hours": "Controls the amount of standby history used for learning.",
    "standby_threshold_w": (
        "Controls the power boundary between standby draw and active use."
    ),
    "always_on_alert_w": (
        "Controls when always-on standby draw becomes worth surfacing."
    ),
    "standby_min_samples": (
        "Controls how many standby samples are required before standby guidance."
    ),
    "leg_imbalance_warning_ratio": (
        "Controls the paired-leg imbalance ratio that triggers split-phase "
        "guidance."
    ),
    "leg_imbalance_min_total_power_w": (
        "Controls the minimum total power required before leg imbalance checks run."
    ),
    "mains_voltage_sag_ratio": (
        "Controls how far mains voltage can sag below baseline before guidance."
    ),
    "mains_voltage_swell_ratio": (
        "Controls how far mains voltage can spike above baseline before guidance."
    ),
    "mains_frequency_drop_hz": (
        "Controls how far mains frequency can drop below baseline before guidance."
    ),
    "mains_frequency_spike_hz": (
        "Controls how far mains frequency can spike above baseline before guidance."
    ),
    "mains_voltage_imbalance_ratio": (
        "Controls how far apart the two mains leg-voltage readings can be before "
        "voltage imbalance guidance appears."
    ),
    "apparent_power_tolerance_percent": (
        "Controls the allowed difference between reported real and apparent power."
    ),
    "power_factor_tolerance": (
        "Controls the allowed power-factor relationship drift."
    ),
    "minimum_apparent_power_va": (
        "Controls the low-load cutoff for metric consistency checks."
    ),
    "balance_negative_tolerance_w": (
        "Controls how much negative mains-minus-load balance is tolerated."
    ),
    "export_tolerance_w": (
        "Controls how much solar export mismatch is tolerated."
    ),
    "solar_export_tolerance_w": (
        "Controls how much solar export mismatch is tolerated."
    ),
    "solar_surplus_threshold_w": (
        "Controls when solar surplus is high enough for load-shifting guidance."
    ),
    "high_solar_surplus_threshold_w": (
        "Controls when solar surplus is considered especially high."
    ),
    "flexible_load_running_threshold_w": (
        "Controls when a flexible load counts as active for load-shift guidance."
    ),
    "linked_thermostat_entities": (
        "Controls which thermostat zones are associated with this HVAC appliance."
    ),
    "thermostat_temperature_sensor_map": (
        "Controls the indoor temperature source used for each thermostat zone."
    ),
    "blower_represents_gas_heat": (
        "Controls whether a blower is treated as the measurable proxy for "
        "gas-furnace heating."
    ),
    "hvac_efficiency_change_threshold_pct": (
        "Controls how far weather-normalized HVAC runtime may slow before an alert."
    ),
}


def recommendation_setting_default_value(setting_key: str) -> Any:
    """Return the built-in default shown beside a suggested setting."""
    return _SETTING_DEFAULTS.get(setting_key)


def recommendation_setting_control_text(setting_key: str) -> str:
    """Return the user-facing description of what a setting controls."""
    return _SETTING_CONTROL_DESCRIPTIONS.get(
        setting_key,
        f"Controls {friendly_feature_name(setting_key).lower()} for this circuit.",
    )


def recommendation_setting_expected_effect(setting_key: str) -> str:
    """Return the user-facing effect summary for a suggested setting."""
    return _SETTING_EXPECTED_EFFECTS.get(
        setting_key,
        (
            "Tune this setting toward the observed history without requiring "
            "manual threshold math."
        ),
    )


def recommendation_evidence_preview(evidence: Any, *, limit: int = 4) -> str:
    """Return a short, bounded evidence preview for recommendation cards."""
    if not isinstance(evidence, Mapping):
        return ""

    parts: list[str] = []
    for key, value in evidence.items():
        key_text = str(key)
        if is_hidden_recommendation_evidence_key(key_text):
            continue
        if isinstance(value, (Mapping, list, tuple, set)):
            continue
        parts.append(
            f"{friendly_feature_name(key_text)}: {_format_recommendation_value(value)}"
        )
        if len(parts) >= limit:
            break
    return "; ".join(parts)


def is_hidden_recommendation_evidence_key(key: str) -> bool:
    """Return true when evidence should stay out of compact user summaries."""
    normalized = key.lower()
    return (
        "entity" in normalized
        or normalized
        in {"source_entities", "entity_ids", "entities", "weather_context"}
    )


def _format_recommendation_value(value: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
