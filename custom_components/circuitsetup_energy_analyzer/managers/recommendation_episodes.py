from __future__ import annotations

import hashlib

RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS = 100
RECOMMENDATION_NOTIFICATION_EPISODE_FINGERPRINT_VERSION = "sha256:v1"


def compact_settings_recommendation_episode_key(
    episode_key: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Return a bounded duplicate-suppression key for pending recommendations."""
    if len(episode_key) <= RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS:
        return episode_key
    fingerprint = hashlib.sha256(repr(episode_key).encode("utf-8")).hexdigest()
    return (
        ("version", RECOMMENDATION_NOTIFICATION_EPISODE_FINGERPRINT_VERSION),
        ("pending_count", str(len(episode_key))),
        ("fingerprint", fingerprint),
    )
