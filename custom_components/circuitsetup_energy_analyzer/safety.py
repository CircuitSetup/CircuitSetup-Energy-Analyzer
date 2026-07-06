from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .localized_text import translation_text

ELECTRICAL_SAFETY_NOTICE = translation_text("safety", "electrical_notice")

_ELECTRICAL_SAFETY_FEATURE_TOKENS = (
    "capacity",
    "demand",
    "nilm",
)


def feature_needs_electrical_safety_notice(feature: Any) -> bool:
    """Return whether a feature should carry the electrical safety notice."""
    normalized = str(feature or "").strip().lower()
    return any(token in normalized for token in _ELECTRICAL_SAFETY_FEATURE_TOKENS)


def with_electrical_safety_notice(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Return attributes with the shared electrical safety notice included."""
    return {**dict(attributes), "safety_notice": ELECTRICAL_SAFETY_NOTICE}
