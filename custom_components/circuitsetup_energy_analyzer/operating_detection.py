from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from .models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
)
from .normalize import NormalizedCircuitSample

OPERATING_ON_THRESHOLD_W = "operating_on_threshold_w"
OPERATING_OFF_THRESHOLD_W = "operating_off_threshold_w"
OPERATING_ON_DWELL_SECONDS = "operating_on_dwell_seconds"
OPERATING_OFF_DWELL_SECONDS = "operating_off_dwell_seconds"
OPERATING_MERGE_GAP_SECONDS = "operating_merge_gap_seconds"
OPERATING_MAX_SAMPLE_GAP_SECONDS = "operating_max_sample_gap_seconds"
OPERATING_DETECTION_SOURCE = "operating_detection_source"
OPERATING_DETECTION_OVERRIDE_FIELDS = (
    OPERATING_ON_THRESHOLD_W,
    OPERATING_OFF_THRESHOLD_W,
    OPERATING_ON_DWELL_SECONDS,
    OPERATING_OFF_DWELL_SECONDS,
    OPERATING_MERGE_GAP_SECONDS,
)

_GENERIC_PROFILE = {
    "on_threshold_w": 80.0,
    "off_threshold_w": 30.0,
    "on_dwell_seconds": 10.0,
    "off_dwell_seconds": 30.0,
    "merge_gap_seconds": 60.0,
    "max_sample_gap_seconds": 600.0,
}

_PROFILE_DEFAULTS: dict[ApplianceProfile, dict[str, float]] = {
    ApplianceProfile.REFRIGERATOR: {
        "on_threshold_w": 25.0,
        "off_threshold_w": 10.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 90.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.FREEZER: {
        "on_threshold_w": 25.0,
        "off_threshold_w": 10.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 90.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.HVAC: {
        "on_threshold_w": 250.0,
        "off_threshold_w": 100.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 60.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.HVAC_COMPRESSOR: {
        "on_threshold_w": 500.0,
        "off_threshold_w": 200.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 60.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.HEAT_PUMP: {
        "on_threshold_w": 500.0,
        "off_threshold_w": 200.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 60.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.MINI_SPLIT: {
        "on_threshold_w": 100.0,
        "off_threshold_w": 40.0,
        "on_dwell_seconds": 30.0,
        "off_dwell_seconds": 180.0,
        "merge_gap_seconds": 300.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.HVAC_BLOWER: {
        "on_threshold_w": 80.0,
        "off_threshold_w": 30.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 60.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.ELECTRIC_HEAT: {
        "on_threshold_w": 500.0,
        "off_threshold_w": 200.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.WATER_HEATER: {
        "on_threshold_w": 500.0,
        "off_threshold_w": 200.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.OVEN: {
        "on_threshold_w": 500.0,
        "off_threshold_w": 200.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.MICROWAVE: {
        "on_threshold_w": 500.0,
        "off_threshold_w": 200.0,
        "on_dwell_seconds": 2.0,
        "off_dwell_seconds": 5.0,
        "merge_gap_seconds": 10.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.DISHWASHER: {
        "on_threshold_w": 20.0,
        "off_threshold_w": 8.0,
        "on_dwell_seconds": 15.0,
        "off_dwell_seconds": 90.0,
        "merge_gap_seconds": 300.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.THREE_D_PRINTER: {
        "on_threshold_w": 35.0,
        "off_threshold_w": 20.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 90.0,
        "merge_gap_seconds": 180.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.WASHER: {
        "on_threshold_w": 20.0,
        "off_threshold_w": 8.0,
        "on_dwell_seconds": 15.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 180.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.DRYER: {
        "on_threshold_w": 100.0,
        "off_threshold_w": 40.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.POOL_PUMP: {
        "on_threshold_w": 100.0,
        "off_threshold_w": 40.0,
        "on_dwell_seconds": 5.0,
        "off_dwell_seconds": 30.0,
        "merge_gap_seconds": 60.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.WATER_PUMP: {
        "on_threshold_w": 100.0,
        "off_threshold_w": 40.0,
        "on_dwell_seconds": 5.0,
        "off_dwell_seconds": 30.0,
        "merge_gap_seconds": 60.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.WELL_PUMP: {
        "on_threshold_w": 100.0,
        "off_threshold_w": 40.0,
        "on_dwell_seconds": 5.0,
        "off_dwell_seconds": 30.0,
        "merge_gap_seconds": 60.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.SUMP_PUMP: {
        "on_threshold_w": 80.0,
        "off_threshold_w": 30.0,
        "on_dwell_seconds": 5.0,
        "off_dwell_seconds": 30.0,
        "merge_gap_seconds": 60.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.EV_CHARGER: {
        "on_threshold_w": 500.0,
        "off_threshold_w": 200.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 60.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.SOLAR_INVERTER: {
        "on_threshold_w": 80.0,
        "off_threshold_w": 30.0,
        "on_dwell_seconds": 15.0,
        "off_dwell_seconds": 60.0,
        "merge_gap_seconds": 120.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.MOTOR_LOAD: {
        "on_threshold_w": 80.0,
        "off_threshold_w": 30.0,
        "on_dwell_seconds": 5.0,
        "off_dwell_seconds": 30.0,
        "merge_gap_seconds": 60.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.RESISTIVE_LOAD: {
        "on_threshold_w": 100.0,
        "off_threshold_w": 40.0,
        "on_dwell_seconds": 10.0,
        "off_dwell_seconds": 45.0,
        "merge_gap_seconds": 90.0,
        "max_sample_gap_seconds": 600.0,
    },
    ApplianceProfile.MIXED: _GENERIC_PROFILE,
    ApplianceProfile.MAINS_NILM: _GENERIC_PROFILE,
}

PROFILE_RUNNING_ON_THRESHOLDS_W = {
    profile: values["on_threshold_w"] for profile, values in _PROFILE_DEFAULTS.items()
}


class OperatingThresholdSource(StrEnum):
    PROFILE_DEFAULT = "profile_default"
    USER_OVERRIDE = "user_override"
    LEARNED_RECOMMENDATION = "learned_recommendation"


@dataclass(frozen=True, slots=True)
class OperatingDetectionProfile:
    on_threshold_w: float
    off_threshold_w: float
    on_dwell_seconds: float
    off_dwell_seconds: float
    merge_gap_seconds: float
    max_sample_gap_seconds: float
    emit_initial_transition: bool = False

    def __post_init__(self) -> None:
        values = (
            self.on_threshold_w,
            self.off_threshold_w,
            self.on_dwell_seconds,
            self.off_dwell_seconds,
            self.merge_gap_seconds,
            self.max_sample_gap_seconds,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Operating detection values must be finite.")
        if self.on_threshold_w <= self.off_threshold_w or self.off_threshold_w < 0.0:
            raise ValueError(
                "on_threshold_w must be greater than off_threshold_w >= 0."
            )
        if self.on_dwell_seconds < 0.0 or self.off_dwell_seconds < 0.0:
            raise ValueError("Dwell values must be nonnegative.")
        if self.merge_gap_seconds < 0.0:
            raise ValueError("merge_gap_seconds must be nonnegative.")
        if self.max_sample_gap_seconds <= 0.0:
            raise ValueError("max_sample_gap_seconds must be positive.")


@dataclass(frozen=True, slots=True)
class ResolvedOperatingDetection:
    profile: OperatingDetectionProfile
    source: OperatingThresholdSource
    appliance_profile: ApplianceProfile
    circuit_mode: CircuitMode


class OperatingState(StrEnum):
    UNKNOWN = "unknown"
    OFF = "off"
    PENDING_ON = "pending_on"
    RUNNING = "running"
    PENDING_OFF = "pending_off"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class OperatingStateSnapshot:
    state: OperatingState
    stable_state: OperatingState
    state_since: datetime | None
    candidate_since: datetime | None
    last_sample_at: datetime | None
    last_power_w: float | None
    on_threshold_w: float
    off_threshold_w: float
    threshold_source: OperatingThresholdSource
    transition_reason: str


@dataclass(frozen=True, slots=True)
class OperatingDetectionResult:
    snapshot: OperatingStateSnapshot
    events: tuple[CircuitEvent, ...] = ()


def resolve_operating_detection(
    config: CircuitConfig,
    overrides: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None,
    source_hint: OperatingThresholdSource | str | None = None,
) -> ResolvedOperatingDetection:
    defaults = dict(_PROFILE_DEFAULTS.get(config.appliance_profile, _GENERIC_PROFILE))
    source = OperatingThresholdSource.PROFILE_DEFAULT
    raw = recommendation or {}
    if raw:
        source = OperatingThresholdSource.LEARNED_RECOMMENDATION
    if overrides:
        raw = overrides
        source = (
            _coerce_operating_threshold_source(source_hint)
            or OperatingThresholdSource.USER_OVERRIDE
        )
    values = {
        "on_threshold_w": _float_value(
            raw.get(OPERATING_ON_THRESHOLD_W),
            defaults["on_threshold_w"],
        ),
        "off_threshold_w": _float_value(
            raw.get(OPERATING_OFF_THRESHOLD_W),
            defaults["off_threshold_w"],
        ),
        "on_dwell_seconds": _float_value(
            raw.get(OPERATING_ON_DWELL_SECONDS),
            defaults["on_dwell_seconds"],
        ),
        "off_dwell_seconds": _float_value(
            raw.get(OPERATING_OFF_DWELL_SECONDS),
            defaults["off_dwell_seconds"],
        ),
        "merge_gap_seconds": _float_value(
            raw.get(OPERATING_MERGE_GAP_SECONDS),
            defaults["merge_gap_seconds"],
        ),
        "max_sample_gap_seconds": _float_value(
            raw.get(OPERATING_MAX_SAMPLE_GAP_SECONDS),
            defaults["max_sample_gap_seconds"],
        ),
    }
    profile = OperatingDetectionProfile(**values)
    return ResolvedOperatingDetection(
        profile=profile,
        source=source,
        appliance_profile=config.appliance_profile,
        circuit_mode=config.mode,
    )


def operating_detection_override_settings(
    settings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(settings, Mapping):
        return {}
    return {
        key: settings[key]
        for key in OPERATING_DETECTION_OVERRIDE_FIELDS
        if key in settings
    }


def operating_detection_source_hint(
    settings: Mapping[str, Any] | None,
) -> OperatingThresholdSource | None:
    if not isinstance(settings, Mapping):
        return None
    return _coerce_operating_threshold_source(
        settings.get(OPERATING_DETECTION_SOURCE),
    )


def resolve_operating_detection_from_settings(
    config: CircuitConfig,
    settings: Mapping[str, Any] | None,
) -> ResolvedOperatingDetection:
    return resolve_operating_detection(
        config,
        overrides=operating_detection_override_settings(settings),
        source_hint=operating_detection_source_hint(settings),
    )


def operating_snapshot_to_dict(snapshot: OperatingStateSnapshot) -> dict[str, Any]:
    return {
        "state": snapshot.state.value,
        "stable_state": snapshot.stable_state.value,
        "state_since": _isoformat_or_none(snapshot.state_since),
        "candidate_since": _isoformat_or_none(snapshot.candidate_since),
        "last_sample_at": _isoformat_or_none(snapshot.last_sample_at),
        "last_power_w": snapshot.last_power_w,
        "on_threshold_w": snapshot.on_threshold_w,
        "off_threshold_w": snapshot.off_threshold_w,
        "threshold_source": snapshot.threshold_source.value,
        "transition_reason": snapshot.transition_reason,
    }


def operating_state_is_running(
    snapshot: OperatingStateSnapshot | Mapping[str, Any] | None,
) -> bool | None:
    if snapshot is None:
        return None
    if isinstance(snapshot, Mapping):
        state_value = str(snapshot.get("state", "")).strip().lower()
        stable_state_value = str(
            snapshot.get("stable_state", state_value)
        ).strip().lower()
    else:
        state_value = snapshot.state.value
        stable_state_value = snapshot.stable_state.value
    if state_value in {
        OperatingState.UNKNOWN.value,
        OperatingState.UNAVAILABLE.value,
    }:
        return None
    return stable_state_value == OperatingState.RUNNING.value


class OperatingStateMachine:
    def __init__(
        self,
        resolved: ResolvedOperatingDetection,
        *,
        voltage_sag_ratio: float = 0.08,
    ) -> None:
        self._resolved = resolved
        self._profile = resolved.profile
        self._voltage_sag_ratio = voltage_sag_ratio
        self._state = OperatingState.UNKNOWN
        self._stable_state = OperatingState.UNKNOWN
        self._state_since: datetime | None = None
        self._candidate_since: datetime | None = None
        self._last_sample_at: datetime | None = None
        self._last_valid_power_at: datetime | None = None
        self._last_power_w: float | None = None
        self._last_on_power_w: float | None = None
        self._run_started_at: datetime | None = None
        self._nominal_voltage: float | None = None
        self._sag_emitted_for_run = False
        self._transition_reason = "startup"

    def process(self, sample: NormalizedCircuitSample) -> OperatingDetectionResult:
        if self._last_sample_at is not None:
            if sample.timestamp < self._last_sample_at:
                return self._result("out_of_order_sample_ignored")
            if sample.timestamp == self._last_sample_at:
                return self._result("duplicate_timestamp_ignored")

        if (
            self._last_sample_at is not None
            and (sample.timestamp - self._last_sample_at).total_seconds()
            > self._profile.max_sample_gap_seconds
        ):
            self._reset_pending_state(sample.timestamp)

        self._last_sample_at = sample.timestamp
        watts = _finite_or_none(sample.real_power)
        self._last_power_w = watts

        if watts is None:
            return self._handle_invalid_or_missing_power(sample)

        self._last_valid_power_at = sample.timestamp

        if self._state is OperatingState.UNKNOWN:
            return self._initialize_from_first_valid_sample(sample, watts)

        if self._stable_state in {
            OperatingState.UNKNOWN,
            OperatingState.UNAVAILABLE,
        }:
            result = self._process_from_unknown(sample, watts)
        elif self._stable_state is OperatingState.OFF:
            result = self._process_from_off(sample, watts)
        else:
            result = self._process_from_running(sample, watts)

        if (
            self._stable_state is OperatingState.RUNNING
            and watts is not None
            and self._state is not OperatingState.PENDING_OFF
        ):
            self._last_on_power_w = watts
            if not self._sag_emitted_for_run:
                sag_event = self._detect_voltage_sag(sample)
                if sag_event is not None:
                    result = OperatingDetectionResult(
                        snapshot=result.snapshot,
                        events=(*result.events, sag_event),
                    )
                    self._sag_emitted_for_run = True

        return result

    def _initialize_from_first_valid_sample(
        self,
        sample: NormalizedCircuitSample,
        watts: float,
    ) -> OperatingDetectionResult:
        if watts >= self._profile.on_threshold_w:
            if self._profile.on_dwell_seconds <= 0.0:
                self._set_running(sample.timestamp, emit_event=False, start_known=False)
                return self._result("initial_running_without_event")
            self._state = OperatingState.PENDING_ON
            self._stable_state = OperatingState.UNKNOWN
            self._candidate_since = sample.timestamp
            self._transition_reason = "initial_above_on_threshold"
            return self._result(self._transition_reason)

        self._state = OperatingState.OFF
        self._stable_state = OperatingState.OFF
        self._state_since = sample.timestamp
        self._candidate_since = None
        self._transition_reason = "initial_below_on_threshold"
        if sample.voltage is not None:
            self._nominal_voltage = sample.voltage
        return self._result(self._transition_reason)

    def _process_from_off(
        self,
        sample: NormalizedCircuitSample,
        watts: float,
    ) -> OperatingDetectionResult:
        if watts >= self._profile.on_threshold_w:
            if self._state is not OperatingState.PENDING_ON:
                self._state = OperatingState.PENDING_ON
                self._candidate_since = sample.timestamp
                self._transition_reason = "pending_on"
                return self._result(self._transition_reason)
            if self._candidate_since is not None and (
                sample.timestamp - self._candidate_since
            ).total_seconds() >= self._profile.on_dwell_seconds:
                event_timestamp = self._candidate_since
                self._set_running(
                    sample.timestamp,
                    emit_event=True,
                    start_known=True,
                )
                return OperatingDetectionResult(
                    snapshot=self._snapshot("confirmed_start"),
                    events=(
                        CircuitEvent(
                            timestamp=event_timestamp,
                            circuit_id=sample.circuit_id,
                            event_type=EventType.START,
                            features=_power_features(sample, "startup_power_w", watts),
                        ),
                    ),
                )
            return self._result("pending_on")

        return self._set_off_without_event(
            sample,
            reason=(
                "pending_on_cancelled"
                if watts > self._profile.off_threshold_w
                else "off_below_threshold"
            ),
        )

    def _process_from_running(
        self,
        sample: NormalizedCircuitSample,
        watts: float,
    ) -> OperatingDetectionResult:
        if watts <= self._profile.off_threshold_w:
            if self._state is not OperatingState.PENDING_OFF:
                self._state = OperatingState.PENDING_OFF
                self._candidate_since = sample.timestamp
                self._transition_reason = "pending_off"
                return self._result(self._transition_reason)
            if self._candidate_since is not None and (
                sample.timestamp - self._candidate_since
            ).total_seconds() >= self._profile.off_dwell_seconds:
                event_timestamp = self._candidate_since
                run_started_at = self._run_started_at
                features = _power_features(
                    sample,
                    "stop_power_w",
                    self._last_on_power_w or watts,
                )
                if run_started_at is not None and event_timestamp is not None:
                    features["run_duration_s"] = (
                        event_timestamp - run_started_at
                    ).total_seconds()
                self._set_off(sample.timestamp)
                if run_started_at is None:
                    return self._result("unknown_start_ended")
                return OperatingDetectionResult(
                    snapshot=self._snapshot("confirmed_stop"),
                    events=(
                        CircuitEvent(
                            timestamp=event_timestamp,
                            circuit_id=sample.circuit_id,
                            event_type=EventType.STOP,
                            features=features,
                        ),
                    ),
                )
            return self._result("pending_off")

        self._state = OperatingState.RUNNING
        self._stable_state = OperatingState.RUNNING
        self._candidate_since = None
        self._transition_reason = (
            "pending_off_cancelled"
            if watts < self._profile.on_threshold_w
            else "running_above_threshold"
        )
        return self._result(self._transition_reason)

    def _process_from_unknown(
        self,
        sample: NormalizedCircuitSample,
        watts: float,
    ) -> OperatingDetectionResult:
        if watts >= self._profile.on_threshold_w:
            if self._candidate_since is not None and (
                sample.timestamp - self._candidate_since
            ).total_seconds() >= self._profile.on_dwell_seconds:
                self._set_running(
                    sample.timestamp,
                    emit_event=False,
                    start_known=False,
                )
                return self._result("initial_running_without_event")
            self._state = OperatingState.PENDING_ON
            self._stable_state = OperatingState.UNKNOWN
            self._candidate_since = self._candidate_since or sample.timestamp
            self._transition_reason = "initial_above_on_threshold"
            return self._result(self._transition_reason)

        return self._set_off_without_event(
            sample,
            reason="initial_above_threshold_cancelled",
        )

    def _set_running(
        self,
        timestamp: datetime,
        *,
        emit_event: bool,
        start_known: bool,
    ) -> None:
        self._state = OperatingState.RUNNING
        self._stable_state = OperatingState.RUNNING
        effective_timestamp = self._candidate_since or timestamp
        self._state_since = effective_timestamp
        self._candidate_since = None
        self._transition_reason = "confirmed_start"
        self._run_started_at = (
            effective_timestamp if emit_event and start_known else None
        )
        self._sag_emitted_for_run = False

    def _set_off(self, timestamp: datetime) -> None:
        self._state = OperatingState.OFF
        self._stable_state = OperatingState.OFF
        self._state_since = self._candidate_since or timestamp
        self._candidate_since = None
        self._transition_reason = "confirmed_stop"
        self._run_started_at = None
        self._last_on_power_w = None
        self._sag_emitted_for_run = False

    def _set_unavailable(self, timestamp: datetime, *, reason: str) -> None:
        self._state = OperatingState.UNAVAILABLE
        self._stable_state = OperatingState.UNAVAILABLE
        self._state_since = timestamp
        self._candidate_since = None
        self._transition_reason = reason
        self._run_started_at = None
        self._last_on_power_w = None
        self._sag_emitted_for_run = False

    def _reset_pending_state(self, timestamp: datetime) -> None:
        if self._state is OperatingState.PENDING_ON:
            self._state = (
                OperatingState.OFF
                if self._stable_state is OperatingState.OFF
                else self._stable_state
            )
            self._candidate_since = None
            self._transition_reason = "pending_on_reset_after_gap"
        elif self._state is OperatingState.PENDING_OFF:
            self._state = OperatingState.RUNNING
            self._stable_state = OperatingState.RUNNING
            self._candidate_since = None
            self._transition_reason = "pending_off_reset_after_gap"

    def _handle_invalid_or_missing_power(
        self,
        sample: NormalizedCircuitSample,
    ) -> OperatingDetectionResult:
        if (
            sample.voltage is not None
            and self._stable_state is not OperatingState.RUNNING
        ):
            self._nominal_voltage = sample.voltage

        if self._should_mark_unavailable(sample):
            stop_event = self._unavailable_stop_event(sample)
            self._set_unavailable(sample.timestamp, reason="source_data_unavailable")
            if stop_event is not None:
                return OperatingDetectionResult(
                    snapshot=self._snapshot("source_data_unavailable"),
                    events=(stop_event,),
                )
            return self._result("source_data_unavailable")

        if self._state in {OperatingState.PENDING_ON, OperatingState.PENDING_OFF}:
            self._reset_pending_state(sample.timestamp)

        return self._result("invalid_or_missing_power")

    def _should_mark_unavailable(self, sample: NormalizedCircuitSample) -> bool:
        if self._last_valid_power_at is None:
            return True
        return (
            sample.timestamp - self._last_valid_power_at
        ).total_seconds() > self._profile.max_sample_gap_seconds

    def _set_off_without_event(
        self,
        sample: NormalizedCircuitSample,
        *,
        reason: str,
    ) -> OperatingDetectionResult:
        self._state = OperatingState.OFF
        previous_stable_state = self._stable_state
        self._stable_state = OperatingState.OFF
        if previous_stable_state is not OperatingState.OFF or self._state_since is None:
            self._state_since = sample.timestamp
        self._candidate_since = None
        self._transition_reason = reason
        if sample.voltage is not None:
            self._nominal_voltage = sample.voltage
        return self._result(reason)

    def _unavailable_stop_event(
        self,
        sample: NormalizedCircuitSample,
    ) -> CircuitEvent | None:
        if (
            self._stable_state is not OperatingState.RUNNING
            or self._run_started_at is None
            or self._last_valid_power_at is None
        ):
            return None

        stop_timestamp = min(
            sample.timestamp,
            self._last_valid_power_at
            + timedelta(seconds=self._profile.max_sample_gap_seconds),
        )
        features = {
            "stop_power_w": float(
                self._last_on_power_w
                if self._last_on_power_w is not None
                else 0.0
            ),
            "run_duration_s": (stop_timestamp - self._run_started_at).total_seconds(),
            "transition_reason": "source_data_unavailable",
        }
        return CircuitEvent(
            timestamp=stop_timestamp,
            circuit_id=sample.circuit_id,
            event_type=EventType.STOP,
            features=features,
        )

    def _detect_voltage_sag(
        self,
        sample: NormalizedCircuitSample,
    ) -> CircuitEvent | None:
        if (
            self._nominal_voltage is None
            or sample.voltage is None
            or sample.real_power is None
            or self._nominal_voltage <= 0.0
        ):
            return None

        sag_ratio = (self._nominal_voltage - sample.voltage) / self._nominal_voltage
        if sag_ratio < self._voltage_sag_ratio:
            return None

        return CircuitEvent(
            timestamp=sample.timestamp,
            circuit_id=sample.circuit_id,
            event_type=EventType.VOLTAGE_SAG,
            features={
                "voltage": sample.voltage,
                "nominal_voltage": self._nominal_voltage,
                "sag_ratio": sag_ratio,
                "real_power_w": sample.real_power,
            },
        )

    def _result(self, reason: str) -> OperatingDetectionResult:
        return OperatingDetectionResult(snapshot=self._snapshot(reason))

    def _snapshot(self, reason: str) -> OperatingStateSnapshot:
        self._transition_reason = reason
        return OperatingStateSnapshot(
            state=self._state,
            stable_state=self._stable_state,
            state_since=self._state_since,
            candidate_since=self._candidate_since,
            last_sample_at=self._last_sample_at,
            last_power_w=self._last_power_w,
            on_threshold_w=self._profile.on_threshold_w,
            off_threshold_w=self._profile.off_threshold_w,
            threshold_source=self._resolved.source,
            transition_reason=reason,
        )


def _power_features(
    sample: NormalizedCircuitSample,
    primary_key: str,
    watts: float,
) -> dict[str, float | str]:
    features: dict[str, float | str] = {primary_key: watts}
    raw_real_power = getattr(sample, "raw_real_power", None)
    if raw_real_power is not None:
        features["raw_real_power_w"] = float(raw_real_power)
    power_flow_direction = getattr(sample, "power_flow_direction", None)
    if power_flow_direction:
        features["power_flow_direction"] = str(power_flow_direction)
    return features


def _float_value(value: Any, default: float) -> float:
    if value is None or value == "":
        return float(default)
    return float(value)


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _coerce_operating_threshold_source(
    value: OperatingThresholdSource | str | None,
) -> OperatingThresholdSource | None:
    if isinstance(value, OperatingThresholdSource):
        return value
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    try:
        return OperatingThresholdSource(normalized)
    except ValueError:
        return None


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
