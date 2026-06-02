from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from .discovery import DiscoveredSensor
from .models import SensorRole

_CHANNEL_PATTERN = re.compile(
    r"(?:^|[^a-z0-9])(?:ch|channel|ct)\s*[_-]?\s*(\d+)(?:$|[^a-z0-9])",
    re.IGNORECASE,
)
_GENERIC_NAME_TOKENS = {
    "a",
    "amp",
    "amps",
    "channel",
    "ch",
    "ct",
    "kw",
    "l1",
    "l2",
    "leg",
    "power",
    "real",
    "sensor",
    "w",
    "watt",
    "watts",
}


@dataclass(frozen=True, slots=True)
class ChannelGroup:
    group_id: str
    sensors: tuple[DiscoveredSensor, ...]

    def has_role(self, role: SensorRole) -> bool:
        return any(sensor.role is role for sensor in self.sensors)


@dataclass(frozen=True, slots=True)
class DualPhaseSuggestion:
    left: DiscoveredSensor
    right: DiscoveredSensor
    confidence: float
    reasons: tuple[str, ...]


def suggest_dual_phase_pairs(
    candidates: list[DiscoveredSensor],
) -> list[DualPhaseSuggestion]:
    real_power_sensors = [
        sensor for sensor in candidates if sensor.role is SensorRole.REAL_POWER
    ]
    suggestions: list[DualPhaseSuggestion] = []

    for left, right in combinations(real_power_sensors, 2):
        left_channel = _channel_number(left)
        right_channel = _channel_number(right)
        if (
            left_channel is not None
            and right_channel is not None
            and left_channel == right_channel
        ):
            continue

        confidence, reasons = _score_pair(left, right, left_channel, right_channel)
        if confidence >= 0.35:
            suggestions.append(
                DualPhaseSuggestion(
                    left=left,
                    right=right,
                    confidence=confidence,
                    reasons=tuple(reasons),
                )
            )

    return sorted(
        suggestions,
        key=lambda suggestion: suggestion.confidence,
        reverse=True,
    )


def _score_pair(
    left: DiscoveredSensor,
    right: DiscoveredSensor,
    left_channel: int | None,
    right_channel: int | None,
) -> tuple[float, list[str]]:
    confidence = 0.0
    reasons: list[str] = []

    if left.device_id is not None and left.device_id == right.device_id:
        confidence += 0.25
        reasons.append("same device")

    if (
        left_channel is not None
        and right_channel is not None
        and abs(left_channel - right_channel) == 1
    ):
        confidence += 0.35
        reasons.append("neighboring channels")

    shared_tokens = _useful_name_tokens(left) & _useful_name_tokens(right)
    if shared_tokens:
        confidence += min(len(shared_tokens) * 0.15, 0.3)
        reasons.append("shared name tokens")

    return confidence, reasons


def _channel_number(sensor: DiscoveredSensor) -> int | None:
    text = f"{sensor.entity_id} {sensor.name}"
    match = _CHANNEL_PATTERN.search(text)
    if match is None:
        return None
    return int(match.group(1))


def _useful_name_tokens(sensor: DiscoveredSensor) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", sensor.name.lower())
    return {
        token
        for token in tokens
        if len(token) > 1 and token not in _GENERIC_NAME_TOKENS and not token.isdigit()
    }
