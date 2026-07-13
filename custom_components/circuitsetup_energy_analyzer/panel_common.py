"""Small shared helpers for panel payload modules."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .localized_text import translation_text
from .models import CircuitConfig
from .settings_preview import (
    build_setting_impact_preview,
    setting_preview_observations,
)


def _panel_text(*keys: str) -> str:
    return translation_text("panel", *keys)


def _add_setting_impact_preview(payload: dict[str, Any], coordinator: Any) -> None:
    setting_key = str(payload.get("setting_key") or "").strip()
    circuit_id = str(payload.get("circuit_id") or "").strip()
    if (
        not setting_key
        or not circuit_id
        or "current_value" not in payload
        or "suggested_value" not in payload
    ):
        return
    clock = getattr(coordinator, "current_time", None)
    now = clock() if callable(clock) else datetime.now(UTC)
    preview = build_setting_impact_preview(
        setting_key,
        payload["current_value"],
        payload["suggested_value"],
        setting_preview_observations(
            getattr(coordinator, "store_data", None),
            circuit_id,
            setting_key,
        ),
        now=now,
    )
    payload["impact_preview"] = preview.as_dict()


def _datetime_from_iso(value: Any) -> datetime | None:
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iter_items(value: Any) -> Iterable[Any]:
    if isinstance(value, (str, bytes)) or value is None:
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()


def _circuit_payload(config: CircuitConfig | None) -> dict[str, str] | None:
    if config is None:
        return None
    return {
        "circuit_id": config.circuit_id,
        "name": config.name,
        "appliance_profile": str(config.appliance_profile),
        "mode": str(config.mode),
    }
