from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..state import circuit_is_learning

SETTINGS_SUGGESTIONS_ATTRIBUTE_MAX_ITEMS = 5
SETTINGS_SUGGESTIONS_ATTRIBUTE_FIELDS = (
    "recommendation_id",
    "setting_key",
    "setting_label",
    "current_value",
    "suggested_value",
    "unit",
    "confidence",
)


def settings_suggestions_value(state: Any, circuit_id: str) -> int:
    """Return the pending settings recommendation count for a circuit."""
    return int(
        getattr(state, "settings_recommendation_count_by_circuit", {}).get(
            circuit_id,
            0,
        )
    )


def settings_suggestions_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return pending settings recommendations for dashboard and automation use."""
    recommendations = getattr(
        state,
        "settings_recommendations_by_circuit",
        {},
    ).get(circuit_id, [])
    recommendation_items = (
        list(recommendations)
        if isinstance(recommendations, Iterable)
        and not isinstance(recommendations, (str, bytes))
        else []
    )
    shown_recommendations = [
        _setting_recommendation_attribute_preview(recommendation)
        for recommendation in recommendation_items[
            :SETTINGS_SUGGESTIONS_ATTRIBUTE_MAX_ITEMS
        ]
    ]
    return {
        "pending_count": settings_suggestions_value(state, circuit_id),
        "learning": circuit_is_learning(state, circuit_id),
        "shown_count": len(shown_recommendations),
        "has_more": len(recommendation_items) > len(shown_recommendations),
        "recommendations": shown_recommendations,
    }


def _setting_recommendation_attribute_preview(
    recommendation: Any,
) -> dict[str, Any]:
    """Return a stable, bounded recommendation preview for entity attributes."""
    return {
        field: value
        for field in SETTINGS_SUGGESTIONS_ATTRIBUTE_FIELDS
        if (value := _recommendation_attribute_value(recommendation, field))
        is not None
    }


def _recommendation_attribute_value(recommendation: Any, field: str) -> Any:
    """Read a recommendation value from dicts or advisor dataclasses."""
    if isinstance(recommendation, Mapping):
        return recommendation.get(field)
    return getattr(recommendation, field, None)

