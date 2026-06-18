from __future__ import annotations

from .models import ApplianceProfile, CircuitEvent, CircuitMode, CircuitSample
from .operating_detection import (
    OperatingDetectionProfile,
    OperatingDetectionResult,
    OperatingStateMachine,
    OperatingStateSnapshot,
    OperatingThresholdSource,
    ResolvedOperatingDetection,
)


class CircuitEventDetector:
    """Detect operating events from a sequence of circuit samples."""

    def __init__(
        self,
        on_threshold_w: float = 80.0,
        off_threshold_w: float = 30.0,
        on_dwell_seconds: float = 10.0,
        off_dwell_seconds: float = 30.0,
        merge_gap_seconds: float = 60.0,
        max_sample_gap_seconds: float = 600.0,
        emit_initial_transition: bool = False,
        voltage_sag_ratio: float = 0.08,
        *,
        appliance_profile: ApplianceProfile = ApplianceProfile.MIXED,
        circuit_mode: CircuitMode = CircuitMode.SINGLE_PHASE,
    ) -> None:
        self._machine = OperatingStateMachine(
            ResolvedOperatingDetection(
                profile=OperatingDetectionProfile(
                    on_threshold_w=on_threshold_w,
                    off_threshold_w=off_threshold_w,
                    on_dwell_seconds=on_dwell_seconds,
                    off_dwell_seconds=off_dwell_seconds,
                    merge_gap_seconds=merge_gap_seconds,
                    max_sample_gap_seconds=max_sample_gap_seconds,
                    emit_initial_transition=emit_initial_transition,
                ),
                source=OperatingThresholdSource.PROFILE_DEFAULT,
                appliance_profile=appliance_profile,
                circuit_mode=circuit_mode,
            ),
            voltage_sag_ratio=voltage_sag_ratio,
        )
        self._last_result: OperatingDetectionResult | None = None

    def process(self, sample: CircuitSample) -> list[CircuitEvent]:
        self._last_result = self._machine.process(sample)
        return list(self._last_result.events)

    @property
    def last_snapshot(self) -> OperatingStateSnapshot | None:
        return (
            self._last_result.snapshot
            if self._last_result is not None
            else None
        )


def _power_features(
    sample: CircuitSample,
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
