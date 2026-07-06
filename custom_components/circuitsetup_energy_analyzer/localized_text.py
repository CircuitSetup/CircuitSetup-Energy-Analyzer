from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

_TRANSLATIONS_PATH = Path(__file__).resolve().parent / "translations" / "en.json"


@lru_cache(maxsize=1)
def english_translations() -> Mapping[str, Any]:
    """Return bundled English translations for custom-rendered text."""
    return json.loads(_TRANSLATIONS_PATH.read_text(encoding="utf-8"))


def translation_section(*keys: str) -> Mapping[str, Any]:
    value = _translation_value(keys)
    return value if isinstance(value, Mapping) else {}


def translation_text(*keys: str) -> str:
    value = _translation_value(keys)
    return str(value) if value is not None else ""


def _translation_value(keys: tuple[str, ...]) -> Any:
    value = _lookup_translation(keys)
    if value is None and keys:
        value = _lookup_translation(("config_panel", *keys))
    return value


def _lookup_translation(keys: tuple[str, ...]) -> Any:
    value: Any = english_translations()
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
        if value is None:
            return None
    return value
