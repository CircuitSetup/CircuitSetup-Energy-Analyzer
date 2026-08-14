"""Mains voltage and frequency excursion detection."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from .baseline import build_baseline
from .models import BaselineStats, CircuitEvent, EventType, Severity
from .normalize import NormalizedCircuitSample

DEFAULT_VOLTAGE_SAG_RATIO = 0.08
DEFAULT_VOLTAGE_SWELL_RATIO = 0.08
DEFAULT_VOLTAGE_IMBALANCE_RATIO = 0.03
DEFAULT_FREQUENCY_DROP_HZ = 0.5
DEFAULT_FREQUENCY_SPIKE_HZ = 0.5
DEFAULT_PRELIMINARY_BASELINE_SAMPLES = 15
DEFAULT_MIN_BASELINE_SAMPLES = 60
DEFAULT_MIN_BASELINE_CONFIDENCE = 0.6
DEFAULT_MIN_EVENT_SAMPLES = 2
DEFAULT_RECOVERY_SAMPLES = 2
DEFAULT_COOLDOWN_SECONDS = 900.0
DEFAULT_BASELINE_WINDOW_SAMPLES = 240
_LEG_VOLTAGE_IMBALANCE_CHANNEL = "leg_voltage_imbalance"
_VOLTAGE_IMBALANCE_METRIC = "voltage_imbalance"
_VOLTAGE_CHANNELS = frozenset({"voltage", "leg_a_voltage", "leg_b_voltage"})
_FREQUENCY_CHANNELS = frozenset({"frequency"})

_UNUSABLE_ISSUE_TOKENS = frozenset(
    {
        "missing",
        "stale",
        "unavailable",
        "unsupported_metadata",
        "non_numeric",
        "non_finite",
        "metadata role conflict",
        "future_timestamp",
        "naive_timestamp",
    }
)


@dataclass(frozen=True, slots=True)
class MainsPowerQualitySettings:
    """Thresholds and learning gates for mains power quality detection."""

    voltage_sag_ratio: float = DEFAULT_VOLTAGE_SAG_RATIO
    voltage_swell_ratio: float = DEFAULT_VOLTAGE_SWELL_RATIO
    voltage_imbalance_ratio: float = DEFAULT_VOLTAGE_IMBALANCE_RATIO
    frequency_drop_hz: float = DEFAULT_FREQUENCY_DROP_HZ
    frequency_spike_hz: float = DEFAULT_FREQUENCY_SPIKE_HZ
    preliminary_baseline_samples: int = DEFAULT_PRELIMINARY_BASELINE_SAMPLES
    min_baseline_samples: int = DEFAULT_MIN_BASELINE_SAMPLES
    min_baseline_confidence: float = DEFAULT_MIN_BASELINE_CONFIDENCE
    min_event_samples: int = DEFAULT_MIN_EVENT_SAMPLES
    recovery_samples: int = DEFAULT_RECOVERY_SAMPLES
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    baseline_window_samples: int = DEFAULT_BASELINE_WINDOW_SAMPLES
    notifications_enabled: bool = True

    def __post_init__(self) -> None:
        _require_ratio("voltage_sag_ratio", self.voltage_sag_ratio)
        _require_ratio("voltage_swell_ratio", self.voltage_swell_ratio)
        _require_ratio("voltage_imbalance_ratio", self.voltage_imbalance_ratio)
        _require_positive("frequency_drop_hz", self.frequency_drop_hz)
        _require_positive("frequency_spike_hz", self.frequency_spike_hz)
        _require_int_at_least(
            "preliminary_baseline_samples",
            self.preliminary_baseline_samples,
            1,
        )
        _require_int_at_least(
            "min_baseline_samples",
            self.min_baseline_samples,
            self.preliminary_baseline_samples,
        )
        if not 0.0 <= self.min_baseline_confidence <= 1.0:
            raise ValueError("min_baseline_confidence must be between 0 and 1")
        _require_int_at_least("min_event_samples", self.min_event_samples, 1)
        _require_int_at_least("recovery_samples", self.recovery_samples, 1)
        _require_non_negative("cooldown_seconds", self.cooldown_seconds)
        _require_int_at_least(
            "baseline_window_samples",
            self.baseline_window_samples,
            self.min_baseline_samples,
        )


@dataclass(frozen=True, slots=True)
class MainsPowerQualityResult:
    """Events emitted by a mains power quality detector pass."""

    events: tuple[CircuitEvent, ...] = ()
    active_events: tuple[CircuitEvent, ...] = ()


@dataclass(slots=True)
class _ChannelState:
    values: deque[float]
    active_kind: str | None = None
    active_started_at: datetime | None = None
    active_sample_count: int = 0
    recovery_sample_count: int = 0
    event_emitted: bool = False
    last_event: CircuitEvent | None = None


class MainsPowerQualityDetector:
    """Detect sustained mains voltage and frequency excursions from samples."""

    def __init__(self, settings: MainsPowerQualitySettings | None = None) -> None:
        self.settings = settings or MainsPowerQualitySettings()
        self._channels: dict[str, _ChannelState] = {}

    def process(
        self,
        sample: NormalizedCircuitSample,
        *,
        detect_voltage: bool = True,
        detect_frequency: bool = True,
        allowed_voltage_channels: frozenset[str] | None = None,
        detect_leg_voltage_imbalance: bool = True,
        emit_events: bool = True,
    ) -> MainsPowerQualityResult:
        """Process a normalized mains sample and emit mature excursion events."""
        events: list[CircuitEvent] = []
        unusable_channels = _unusable_channels(sample.quality_issues)
        if allowed_voltage_channels is None:
            allowed_voltage_channels = (
                _VOLTAGE_CHANNELS if detect_voltage else frozenset()
            )
        else:
            allowed_voltage_channels = frozenset(allowed_voltage_channels)
            detect_voltage = bool(allowed_voltage_channels)
        for channel in _VOLTAGE_CHANNELS - allowed_voltage_channels:
            self._channels.pop(channel, None)
        if not detect_frequency:
            for channel in _FREQUENCY_CHANNELS:
                self._channels.pop(channel, None)
        for channel, metric, value in _channel_values(sample):
            if metric == "voltage" and channel not in allowed_voltage_channels:
                continue
            if metric == "frequency" and not detect_frequency:
                continue
            if channel in unusable_channels:
                continue
            state = self._channels.setdefault(
                channel,
                _ChannelState(
                    values=deque(maxlen=self.settings.baseline_window_samples),
                ),
            )
            event = self._process_channel(
                sample,
                state,
                channel,
                metric,
                value,
                emit_event=emit_events,
            )
            if event is not None:
                events.append(event)
        if detect_voltage and detect_leg_voltage_imbalance:
            imbalance_event = self._process_leg_voltage_imbalance(
                sample,
                unusable_channels,
                emit_event=emit_events,
            )
            if imbalance_event is not None:
                events.append(imbalance_event)
        else:
            self._channels.pop(_LEG_VOLTAGE_IMBALANCE_CHANNEL, None)
        return MainsPowerQualityResult(
            events=tuple(events),
            active_events=tuple(
                state.last_event
                for state in self._channels.values()
                if state.active_kind is not None and state.last_event is not None
            ),
        )

    def _process_channel(
        self,
        sample: NormalizedCircuitSample,
        state: _ChannelState,
        channel: str,
        metric: str,
        value: float,
        *,
        emit_event: bool,
    ) -> CircuitEvent | None:
        settings = self.settings
        if len(state.values) < settings.preliminary_baseline_samples:
            state.values.append(value)
            return None

        baseline = build_baseline(channel, list(state.values))
        excursion = self._classify(metric, value, baseline)
        if excursion is None:
            _observe_recovery(state, settings.recovery_samples)
            state.values.append(value)
            return None

        event_type, kind = excursion
        if state.active_kind != kind:
            state.active_kind = kind
            state.active_started_at = sample.timestamp
            state.active_sample_count = 1
            state.recovery_sample_count = 0
            state.event_emitted = False
        else:
            state.active_sample_count += 1
            state.recovery_sample_count = 0

        if state.active_sample_count < settings.min_event_samples:
            return None

        baseline_ready = (
            baseline.sample_count >= settings.min_baseline_samples
            and baseline.confidence >= settings.min_baseline_confidence
        )
        event = _event_for_excursion(
            sample,
            event_type,
            channel=channel,
            metric=metric,
            value=value,
            baseline=baseline,
            first_seen=state.active_started_at or sample.timestamp,
            sample_count=state.active_sample_count,
            notification_eligible=(
                settings.notifications_enabled and baseline_ready
            ),
        )
        state.last_event = event
        if state.event_emitted:
            return None
        if not baseline_ready:
            return None
        if not emit_event:
            return None
        state.event_emitted = True
        return event

    def _classify(
        self,
        metric: str,
        value: float,
        baseline: BaselineStats,
    ) -> tuple[EventType, str] | None:
        nominal = baseline.median
        if metric == "voltage":
            if value < nominal * (1.0 - self.settings.voltage_sag_ratio):
                return (EventType.VOLTAGE_SAG, f"{metric}:low")
            if value > nominal * (1.0 + self.settings.voltage_swell_ratio):
                return (EventType.VOLTAGE_SWELL, f"{metric}:high")
            return None
        if value < nominal - self.settings.frequency_drop_hz:
            return (EventType.FREQUENCY_DROP, f"{metric}:low")
        if value > nominal + self.settings.frequency_spike_hz:
            return (EventType.FREQUENCY_SPIKE, f"{metric}:high")
        return None

    def _process_leg_voltage_imbalance(
        self,
        sample: NormalizedCircuitSample,
        unusable_channels: frozenset[str],
        *,
        emit_event: bool,
    ) -> CircuitEvent | None:
        if unusable_channels & {"leg_a_voltage", "leg_b_voltage"}:
            return None
        if not (
            _is_finite_number(sample.leg_a_voltage)
            and _is_finite_number(sample.leg_b_voltage)
        ):
            return None
        leg_a_voltage = float(sample.leg_a_voltage)
        leg_b_voltage = float(sample.leg_b_voltage)
        midpoint = (leg_a_voltage + leg_b_voltage) / 2.0
        if midpoint <= 0.0:
            return None

        ratio = abs(leg_a_voltage - leg_b_voltage) / midpoint
        state = self._channels.setdefault(
            _LEG_VOLTAGE_IMBALANCE_CHANNEL,
            _ChannelState(
                values=deque(maxlen=self.settings.baseline_window_samples),
            ),
        )
        settings = self.settings
        if len(state.values) < settings.preliminary_baseline_samples:
            state.values.append(ratio)
            return None

        baseline = build_baseline(_LEG_VOLTAGE_IMBALANCE_CHANNEL, list(state.values))
        if ratio <= settings.voltage_imbalance_ratio:
            _observe_recovery(state, settings.recovery_samples)
            state.values.append(ratio)
            return None

        if state.active_kind != _VOLTAGE_IMBALANCE_METRIC:
            state.active_kind = _VOLTAGE_IMBALANCE_METRIC
            state.active_started_at = sample.timestamp
            state.active_sample_count = 1
            state.recovery_sample_count = 0
            state.event_emitted = False
        else:
            state.active_sample_count += 1
            state.recovery_sample_count = 0

        if state.active_sample_count < settings.min_event_samples:
            return None

        baseline_ready = (
            baseline.sample_count >= settings.min_baseline_samples
            and baseline.confidence >= settings.min_baseline_confidence
        )
        event = _event_for_voltage_imbalance(
            sample,
            ratio=ratio,
            threshold_ratio=settings.voltage_imbalance_ratio,
            leg_a_voltage=leg_a_voltage,
            leg_b_voltage=leg_b_voltage,
            baseline=baseline,
            first_seen=state.active_started_at or sample.timestamp,
            sample_count=state.active_sample_count,
            notification_eligible=(
                settings.notifications_enabled and baseline_ready
            ),
        )
        state.last_event = event
        if state.event_emitted:
            return None
        if not baseline_ready:
            return None
        if not emit_event:
            return None
        state.event_emitted = True
        return event


def mains_power_quality_settings_from_mapping(
    raw_settings: Mapping[str, Any] | None,
) -> MainsPowerQualitySettings:
    """Build mains power quality settings from per-circuit advanced options."""
    defaults = MainsPowerQualitySettings()
    if not isinstance(raw_settings, Mapping):
        return defaults
    values: dict[str, Any] = {}
    field_names = {field.name for field in fields(MainsPowerQualitySettings)}
    for setting_name in field_names:
        legacy_name = f"mains_power_quality_{setting_name}"
        compact_name = f"mains_{setting_name}"
        if legacy_name in raw_settings:
            values[setting_name] = raw_settings[legacy_name]
        elif compact_name in raw_settings:
            values[setting_name] = raw_settings[compact_name]
        elif setting_name in raw_settings:
            values[setting_name] = raw_settings[setting_name]

    coerced: dict[str, Any] = {}
    for name, value in values.items():
        try:
            if name == "notifications_enabled":
                coerced[name] = _bool_value(value)
            elif name in {
                "preliminary_baseline_samples",
                "min_baseline_samples",
                "min_event_samples",
                "recovery_samples",
                "baseline_window_samples",
            }:
                coerced[name] = _int_value(value)
            else:
                coerced[name] = _float_value(value)
        except (TypeError, ValueError):
            continue
    try:
        return MainsPowerQualitySettings(**coerced)
    except (TypeError, ValueError):
        return defaults


def _event_for_excursion(
    sample: NormalizedCircuitSample,
    event_type: EventType,
    *,
    channel: str,
    metric: str,
    value: float,
    baseline: BaselineStats,
    first_seen: datetime,
    sample_count: int,
    notification_eligible: bool,
) -> CircuitEvent:
    deviation = round(value - baseline.median, 4)
    ratio = round(deviation / baseline.median, 4) if baseline.median else 0.0
    duration_s = max(0.0, (sample.timestamp - first_seen).total_seconds())
    features: dict[str, Any] = {
        "source": "mains_power_quality",
        "channel": channel,
        "metric": metric,
        "observed_value": value,
        "baseline_value": baseline.median,
        "deviation": deviation,
        "deviation_ratio": ratio,
        "sample_count": sample_count,
        "duration_s": duration_s,
        "first_seen": first_seen.isoformat(),
        "last_seen": sample.timestamp.isoformat(),
        "baseline_sample_count": baseline.sample_count,
        "baseline_confidence": baseline.confidence,
        "notification_eligible": notification_eligible,
    }
    if metric == "voltage":
        features["voltage"] = value
        features["nominal_voltage"] = baseline.median
        if event_type is EventType.VOLTAGE_SAG:
            features["sag_ratio"] = round(max(0.0, -ratio), 4)
        else:
            features["swell_ratio"] = round(max(0.0, ratio), 4)
    else:
        features["frequency"] = value
        features["nominal_frequency"] = baseline.median
        features["frequency_delta_hz"] = deviation

    return CircuitEvent(
        timestamp=sample.timestamp,
        circuit_id=sample.circuit_id,
        event_type=event_type,
        severity=Severity.WARNING,
        features=features,
    )


def _event_for_voltage_imbalance(
    sample: NormalizedCircuitSample,
    *,
    ratio: float,
    threshold_ratio: float,
    leg_a_voltage: float,
    leg_b_voltage: float,
    baseline: BaselineStats,
    first_seen: datetime,
    sample_count: int,
    notification_eligible: bool,
) -> CircuitEvent:
    voltage_difference = abs(leg_a_voltage - leg_b_voltage)
    duration_s = max(0.0, (sample.timestamp - first_seen).total_seconds())
    features: dict[str, Any] = {
        "source": "mains_power_quality",
        "channel": _LEG_VOLTAGE_IMBALANCE_CHANNEL,
        "metric": _VOLTAGE_IMBALANCE_METRIC,
        "observed_value": round(ratio, 4),
        "baseline_value": threshold_ratio,
        "deviation": round(ratio - threshold_ratio, 4),
        "deviation_ratio": round(ratio - threshold_ratio, 4),
        "sample_count": sample_count,
        "duration_s": duration_s,
        "first_seen": first_seen.isoformat(),
        "last_seen": sample.timestamp.isoformat(),
        "baseline_sample_count": baseline.sample_count,
        "baseline_confidence": baseline.confidence,
        "notification_eligible": notification_eligible,
        "leg_a_voltage": leg_a_voltage,
        "leg_b_voltage": leg_b_voltage,
        "voltage_difference": round(voltage_difference, 4),
        "voltage_imbalance_ratio": round(ratio, 4),
        "voltage_imbalance_threshold_ratio": threshold_ratio,
    }
    return CircuitEvent(
        timestamp=sample.timestamp,
        circuit_id=sample.circuit_id,
        event_type=EventType.VOLTAGE_IMBALANCE,
        severity=Severity.WARNING,
        features=features,
    )


def _channel_values(
    sample: NormalizedCircuitSample,
) -> Iterable[tuple[str, str, float]]:
    for channel, value in (
        ("voltage", sample.voltage),
        ("leg_a_voltage", sample.leg_a_voltage),
        ("leg_b_voltage", sample.leg_b_voltage),
    ):
        if _is_finite_number(value):
            yield channel, "voltage", float(value)
    if _is_finite_number(sample.frequency):
        yield "frequency", "frequency", float(sample.frequency)


def _observe_recovery(state: _ChannelState, recovery_samples: int) -> None:
    if state.active_kind is None:
        return
    state.recovery_sample_count += 1
    if state.recovery_sample_count >= recovery_samples:
        state.active_kind = None
        state.active_started_at = None
        state.active_sample_count = 0
        state.recovery_sample_count = 0
        state.event_emitted = False
        state.last_event = None


def _unusable_channels(issues: Iterable[str]) -> frozenset[str]:
    channels: set[str] = set()
    for issue in issues:
        normalized = issue.lower()
        if not any(token in normalized for token in _UNUSABLE_ISSUE_TOKENS):
            continue
        if "frequency" in normalized:
            channels.add("frequency")
        if "voltage" in normalized:
            leg = _leg_hint(normalized)
            if leg == "a":
                channels.add("leg_a_voltage")
            elif leg == "b":
                channels.add("leg_b_voltage")
            else:
                channels.add("voltage")
    return frozenset(channels)


def _leg_hint(text: str) -> str | None:
    padded = "_" + "".join(
        character if character.isalnum() else "_" for character in text
    ) + "_"
    if any(
        token in padded
        for token in (
            "_l1_",
            "_leg1_",
            "_leg_1_",
            "_line1_",
            "_line_1_",
            "_phase1_",
            "_phase_1_",
            "_leg_a_",
            "_line_a_",
            "_phase_a_",
        )
    ):
        return "a"
    if any(
        token in padded
        for token in (
            "_l2_",
            "_leg2_",
            "_leg_2_",
            "_line2_",
            "_line_2_",
            "_phase2_",
            "_phase_2_",
            "_leg_b_",
            "_line_b_",
            "_phase_b_",
        )
    ):
        return "b"
    return None


def _is_finite_number(value: float | None) -> bool:
    try:
        return value is not None and math.isfinite(value)
    except TypeError:
        return False


def _require_ratio(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0.0 < value < 1.0:
        raise ValueError(f"{name} must be a finite ratio between 0 and 1")


def _require_positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")


def _require_non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")


def _require_int_at_least(name: str, value: int, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")


def _float_value(value: Any) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("setting must be finite")
    return numeric


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("integer setting must be an integer")
    numeric = int(value)
    if numeric != float(value):
        raise ValueError("integer setting must not have a fractional part")
    return numeric


def _bool_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no"}
    return bool(value)
