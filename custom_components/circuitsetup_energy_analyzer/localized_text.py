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
    value: Any = english_translations()
    for key in keys:
        if not isinstance(value, Mapping):
            return {}
        value = value.get(key)
    return value if isinstance(value, Mapping) else {}


def translation_text(*keys: str) -> str:
    value: Any = english_translations()
    for key in keys:
        if not isinstance(value, Mapping):
            return ""
        value = value.get(key)
    return str(value) if value is not None else ""
